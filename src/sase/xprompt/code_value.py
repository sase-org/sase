"""Python adapter for the Rust `CodeValue` and directive-owned fence scan."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from sase.core.rust import require_rust_binding
from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import current_flags
from sase.xprompt._exceptions import DirectiveError


_OWNED_PLACEHOLDER_PREFIX = "\x00XPC_"
_OWNED_PLACEHOLDER_SUFFIX = "\x00"

TYPED_LAUNCH_UNITS_DISABLED_MESSAGE = (
    "The %if and %proc directives require the typed_launch_units beta flag. "
    "Enable it with `sase flag enable typed_launch_units`. These directives "
    "are never forwarded to the model."
)


@dataclass(frozen=True, slots=True)
class CodeValue:
    """Structured source plus language for `%if`, `%proc`, and `type: code`."""

    source: str
    language: str
    info_string: str | None
    digest: str
    preview: str


@dataclass(frozen=True, slots=True)
class _CodeDirectiveSpan:
    """One captured `%if::` / `%proc::` span with optional structured code."""

    name: str
    span: tuple[int, int]
    code: CodeValue | None


@dataclass(frozen=True, slots=True)
class _CodeDirectiveDiagnostic:
    """Actionable diagnostic from the directive-owned fence scanner."""

    code: str
    message: str
    span: tuple[int, int]


@dataclass(frozen=True, slots=True)
class CodeDirectiveScan:
    """Versioned scan of directive-owned fences."""

    schema_version: int
    directives: tuple[_CodeDirectiveSpan, ...]
    diagnostics: tuple[_CodeDirectiveDiagnostic, ...]


def typed_launch_units_enabled() -> bool:
    """Return the process-local `typed_launch_units` decision."""
    return current_flags().enabled(FeatureFlag.typed_launch_units)


def scan_directive_owned_fences(text: str) -> CodeDirectiveScan:
    """Scan `%if::` / `%proc::` fences via the shared Rust contract."""
    payload = _owned_scanner()(text)
    if not isinstance(payload, dict):
        return CodeDirectiveScan(schema_version=1, directives=(), diagnostics=())
    return _scan_from_wire(text, payload)


def raise_if_code_directive_scan_failed(scan: CodeDirectiveScan) -> None:
    """Raise the first actionable fence diagnostic, if any."""
    if not scan.diagnostics:
        return
    diagnostic = scan.diagnostics[0]
    raise DirectiveError(diagnostic.message)


def reject_disabled_code_directives(
    text: str,
    *,
    scan: CodeDirectiveScan | None = None,
) -> None:
    """Reject explicit `%if` / `%proc` uses while the beta flag is off."""
    if typed_launch_units_enabled():
        return
    resolved = scan if scan is not None else scan_directive_owned_fences(text)
    if resolved.directives or _mentions_code_directive(text):
        raise DirectiveError(TYPED_LAUNCH_UNITS_DISABLED_MESSAGE)


def protect_owned_code_directives(text: str, blocks: list[str]) -> str:
    """Placeholder-protect directive-owned fences before ordinary fence scans."""
    scan = scan_directive_owned_fences(text)
    reject_disabled_code_directives(text, scan=scan)
    if typed_launch_units_enabled():
        raise_if_code_directive_scan_failed(scan)
    spans = [directive.span for directive in scan.directives]
    spans.extend(_proc_paren_spans(text))
    spans = sorted(set(spans), key=lambda item: item[0], reverse=True)
    protected = text
    for start, end in spans:
        idx = len(blocks)
        blocks.append(text[start:end])
        placeholder = f"{_OWNED_PLACEHOLDER_PREFIX}{idx}{_OWNED_PLACEHOLDER_SUFFIX}"
        protected = protected[:start] + placeholder + protected[end:]
    return protected


def unprotect_owned_code_directives(text: str, blocks: list[str]) -> str:
    """Restore directive-owned fence placeholders."""
    for index, block in enumerate(blocks):
        text = text.replace(
            f"{_OWNED_PLACEHOLDER_PREFIX}{index}{_OWNED_PLACEHOLDER_SUFFIX}",
            block,
        )
    return text


def strip_owned_code_spans(text: str, scan: CodeDirectiveScan) -> str:
    """Remove captured directive-owned fences from *text*."""
    stripped = text
    for directive in reversed(scan.directives):
        start, end = directive.span
        stripped = stripped[:start] + stripped[end:]
    return stripped


def make_code_value(
    source: str,
    language: str,
    info_string: str | None = None,
) -> CodeValue:
    """Build a `CodeValue` with the same digest/preview rules as Rust."""
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    line = next((part.strip() for part in source.splitlines() if part.strip()), "")
    cleaned = "".join(" " if ch.isascii() and ord(ch) < 32 else ch for ch in line)
    preview = cleaned if len(cleaned) <= 80 else f"{cleaned[:79]}…"
    return CodeValue(
        source=source,
        language=language,
        info_string=info_string,
        digest=digest,
        preview=preview,
    )


def _code_value_from_wire(payload: Mapping[str, Any] | None) -> CodeValue | None:
    """Rehydrate a `CodeValue` from a Rust wire dict."""
    if not isinstance(payload, Mapping):
        return None
    source = str(payload.get("source") or "")
    language = str(payload.get("language") or "bash")
    info = payload.get("info_string")
    return CodeValue(
        source=source,
        language=language,
        info_string=str(info) if isinstance(info, str) else None,
        digest=str(payload.get("digest") or ""),
        preview=str(payload.get("preview") or ""),
    )


def _scan_from_wire(text: str, payload: Mapping[str, Any]) -> CodeDirectiveScan:
    directives: list[_CodeDirectiveSpan] = []
    for row in payload.get("directives") or []:
        if not isinstance(row, dict):
            continue
        span = _span_from_wire(text, row.get("span"))
        directives.append(
            _CodeDirectiveSpan(
                name=str(row.get("name") or ""),
                span=span,
                code=_code_value_from_wire(
                    row.get("code") if isinstance(row.get("code"), dict) else None
                ),
            )
        )
    diagnostics: list[_CodeDirectiveDiagnostic] = []
    for row in payload.get("diagnostics") or []:
        if not isinstance(row, dict):
            continue
        diagnostics.append(
            _CodeDirectiveDiagnostic(
                code=str(row.get("code") or ""),
                message=str(row.get("message") or ""),
                span=_span_from_wire(text, row.get("span")),
            )
        )
    version = payload.get("schema_version")
    return CodeDirectiveScan(
        schema_version=int(version) if isinstance(version, int) else 1,
        directives=tuple(directives),
        diagnostics=tuple(diagnostics),
    )


def _span_from_wire(text: str, raw: Any) -> tuple[int, int]:
    if not isinstance(raw, list) or len(raw) != 2:
        return (0, 0)
    start = int(raw[0])
    end = int(raw[1])
    return _byte_range_to_character(text, start, end)


def _byte_range_to_character(text: str, start: int, end: int) -> tuple[int, int]:
    if text.isascii():
        return start, end
    mapping = _byte_to_character(text)
    return mapping.get(start, start), mapping.get(end, end)


def _byte_to_character(text: str) -> dict[int, int]:
    mapping: dict[int, int] = {}
    byte_offset = 0
    for character_offset, character in enumerate(text):
        mapping[byte_offset] = character_offset
        byte_offset += len(character.encode("utf-8"))
    mapping[byte_offset] = len(text)
    return mapping


def _mentions_code_directive(text: str) -> bool:
    if "%if" not in text and "%proc" not in text:
        return False
    from sase.xprompt._fenced_blocks import fenced_block_ranges

    fences = fenced_block_ranges(text)
    cursor = 0
    length = len(text)
    while cursor < length:
        index = text.find("%", cursor)
        if index < 0:
            return False
        if any(start <= index < end for start, end in fences):
            cursor = index + 1
            continue
        rest = text[index + 1 :]
        if _is_directive_token(rest, "if") or _is_directive_token(rest, "proc"):
            return True
        cursor = index + 1
    return False


def _proc_paren_spans(text: str) -> list[tuple[int, int]]:
    """Return `%proc(...)` spans so quoted bodies stay opaque during expansion."""
    import re

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._parsing import find_matching_paren_for_args

    spans: list[tuple[int, int]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, text, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "proc" or match.group(2) is None:
            continue
        close = find_matching_paren_for_args(text, match.end() - 1)
        if close is not None:
            spans.append((match.start(), close + 1))
    return spans


def _is_directive_token(rest: str, name: str) -> bool:
    if not rest.startswith(name):
        return False
    if len(rest) == len(name):
        return True
    next_char = rest[len(name)]
    return not (next_char.isalnum() or next_char == "_")


@cache
def _owned_scanner() -> Callable[..., Any]:
    return require_rust_binding("scan_directive_owned_fences")


__all__ = [
    "TYPED_LAUNCH_UNITS_DISABLED_MESSAGE",
    "CodeDirectiveScan",
    "CodeValue",
    "make_code_value",
    "protect_owned_code_directives",
    "raise_if_code_directive_scan_failed",
    "unprotect_owned_code_directives",
    "reject_disabled_code_directives",
    "scan_directive_owned_fences",
    "strip_owned_code_spans",
    "typed_launch_units_enabled",
]
