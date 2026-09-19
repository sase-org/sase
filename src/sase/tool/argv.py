"""Named-tool and ad-hoc argv resolution plus conservative display redaction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Any

from sase.config.tools import ToolCatalog, ToolCatalogError, load_project_tool_catalog
from sase.content_layout import discover_project_root


_SECRET_NAME = re.compile(
    r"(?i)^(password|passwd|secret|token|api[_-]?key|authorization|bearer|"
    r"credential)$"
)
_SECRET_ASSIGN = re.compile(
    r"(?i)^(?:--?)?(password|passwd|secret|token|api[_-]?key|authorization|"
    r"bearer|credential)=.+"
)
_SECRET_INLINE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|bearer|"
    r"credential)\b\s*[:=]\s*\S+"
)


class ToolRunUsageError(ValueError):
    """User-facing usage or catalog error for ``sase tool run`` (exit 2)."""


@dataclass(frozen=True)
class ResolvedToolArgv:
    """Fully resolved execution identity for one foreground invocation."""

    tool_name: str | None
    argv: tuple[str, ...]
    extra_args: tuple[str, ...]
    display_argv: tuple[str, ...]
    private_argv: tuple[str, ...] | None
    definition: dict[str, Any]
    digest: str | None
    cwd: str | None
    adhoc: bool


def _parse_run_words(words: Sequence[str]) -> tuple[bool, str | None, tuple[str, ...]]:
    """Return ``(adhoc, tool_name, extra_or_argv)`` from the run remainder."""

    tokens = [str(part) for part in words]
    if not tokens:
        raise ToolRunUsageError(
            "Usage: sase tool run TOOL [-- ARGS...] or sase tool run -- ARGV..."
        )
    if tokens[0] == "--":
        argv = tuple(tokens[1:])
        if not argv:
            raise ToolRunUsageError("ad-hoc run requires a command after --")
        return True, None, argv
    tool_name = tokens[0]
    if not tool_name or tool_name.startswith("-"):
        raise ToolRunUsageError(
            "Usage: sase tool run TOOL [-- ARGS...] or sase tool run -- ARGV..."
        )
    rest = list(tokens[1:])
    if rest and rest[0] == "--":
        extra = tuple(rest[1:])
    else:
        extra = tuple(rest)
    return False, tool_name, extra


def _redact_display_argv(argv: Sequence[str]) -> list[str]:
    """Redact secret-like flags and payloads for query/display argv."""

    out: list[str] = []
    redact_next = False
    for arg in argv:
        if redact_next:
            out.append("<redacted>")
            redact_next = False
            continue
        if _SECRET_ASSIGN.match(arg):
            key, _, _ = arg.partition("=")
            out.append(f"{key}=<redacted>")
            continue
        if _SECRET_INLINE.search(arg):
            out.append(_SECRET_INLINE.sub(r"\1=<redacted>", arg, count=1))
            continue
        stripped = arg.lstrip("-")
        if _SECRET_NAME.match(stripped):
            out.append(arg)
            redact_next = True
            continue
        out.append(arg)
    if redact_next:
        out.append("<redacted>")
    return out


def resolve_run_argv(words: Sequence[str]) -> ResolvedToolArgv:
    """Resolve catalog or ad-hoc argv without expanding shell syntax."""

    adhoc, tool_name, payload = _parse_run_words(words)
    if adhoc:
        argv = tuple(payload)
        display = tuple(_redact_display_argv(argv))
        private = argv if display != argv else None
        return ResolvedToolArgv(
            tool_name=None,
            argv=argv,
            extra_args=(),
            display_argv=display,
            private_argv=private,
            definition=_adhoc_definition(argv),
            digest=None,
            cwd=None,
            adhoc=True,
        )

    try:
        catalog = load_project_tool_catalog()
    except ToolCatalogError as exc:
        raise ToolRunUsageError(str(exc)) from exc
    entry = _entry_by_name(catalog, str(tool_name))
    if entry is None:
        raise ToolRunUsageError(f"unknown tool {tool_name!r}")
    extra = tuple(payload)
    args_policy = str(entry.definition.get("args") or "deny")
    if extra and args_policy != "allow":
        raise ToolRunUsageError(f"tool {tool_name!r} does not allow extra arguments")
    argv = tuple(str(part) for part in entry.definition.get("argv") or ()) + extra
    display = tuple(_redact_display_argv(argv))
    private = argv if display != argv else None
    root = discover_project_root()
    return ResolvedToolArgv(
        tool_name=entry.name,
        argv=argv,
        extra_args=extra,
        display_argv=display,
        private_argv=private,
        definition=dict(entry.definition),
        digest=entry.digest,
        cwd=str(root) if root is not None else None,
        adhoc=False,
    )


def _entry_by_name(catalog: ToolCatalog, name: str) -> Any | None:
    for entry in catalog.entries:
        if entry.name == name:
            return entry
    return None


def _adhoc_definition(argv: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "ad-hoc",
        "argv": list(argv),
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


__all__ = [
    "ResolvedToolArgv",
    "ToolRunUsageError",
    "resolve_run_argv",
]
