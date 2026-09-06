"""Frontend-agnostic inspection helpers for top-level Jinja2 prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from jinja2 import TemplateSyntaxError, meta

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._literal_zones import code_literal_ranges, literal_zone_ranges
from ._jinja import BUILTIN_RUNTIME_NAMES, RESERVED_GLOBAL_NAMES, get_jinja_env

JinjaSpanKind = Literal[
    "delimiter",
    "statement",
    "variable",
    "comment",
    "filter",
    "keyword",
    "operator",
]

JINJA_KEYWORDS: frozenset[str] = frozenset(
    {
        "and",
        "as",
        "block",
        "break",
        "call",
        "continue",
        "do",
        "elif",
        "else",
        "endblock",
        "endcall",
        "endfilter",
        "endfor",
        "endif",
        "endmacro",
        "endraw",
        "endset",
        "endwith",
        "extends",
        "filter",
        "for",
        "from",
        "if",
        "import",
        "in",
        "include",
        "is",
        "macro",
        "not",
        "or",
        "raw",
        "recursive",
        "required",
        "scoped",
        "set",
        "with",
        "without",
    }
)

_BEGIN_TOKEN_TYPES = {
    "variable_begin": "variable",
    "block_begin": "block",
    "comment_begin": "comment",
}
_END_TOKEN_TYPES = {"variable_end", "block_end", "comment_end"}
_JINJA_MARKER_RE = re.compile(r"\{\{|\{%|\{#")


@dataclass(frozen=True, slots=True)
class JinjaSpan:
    """A Jinja2 syntax span with character offsets in the original prompt."""

    start: int
    end: int
    kind: JinjaSpanKind
    value: str = ""


@dataclass(frozen=True, slots=True)
class JinjaDiagnostics:
    """Parse/lint result for a top-level prompt template."""

    has_jinja: bool
    ok: bool
    message: str | None = None
    lineno: int | None = None
    col: int | None = None
    span: tuple[int, int] | None = None
    unknown_variables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JinjaCompletionContext:
    """The editable token inside a Jinja2 tag at the cursor."""

    replacement_start: int
    replacement_end: int
    prefix: str
    tag_kind: Literal["variable", "block"]
    namespace: str | None = None


RUNTIME_NAMESPACE_MEMBERS: dict[str, frozenset[str]] = {
    "wait": frozenset({"artifacts", "chats"}),
}


def has_jinja(text: str) -> bool:
    """Return True when *text* contains Jinja2 markers outside fenced blocks."""
    masked = _mask_jinja_regions(text)
    return bool(_JINJA_MARKER_RE.search(masked))


def tokenize(text: str) -> list[JinjaSpan]:
    """Return Jinja2 token spans outside fenced code blocks."""
    masked = _mask_jinja_regions(text)
    if not _JINJA_MARKER_RE.search(masked):
        return []

    spans: list[JinjaSpan] = []
    offset = 0
    tag_context: str | None = None
    pending_filter = False

    try:
        stream = get_jinja_env().lex(masked)
        for _lineno, token_type, value in stream:
            start = offset
            end = start + len(value)
            offset = end
            if not value:
                continue

            if token_type in _BEGIN_TOKEN_TYPES:
                tag_context = _BEGIN_TOKEN_TYPES[token_type]
                pending_filter = False
                spans.append(JinjaSpan(start, end, "delimiter", value))
                continue

            if token_type in _END_TOKEN_TYPES:
                spans.append(JinjaSpan(start, end, "delimiter", value))
                tag_context = None
                pending_filter = False
                continue

            if tag_context == "comment":
                spans.append(JinjaSpan(start, end, "comment", value))
                continue

            if tag_context is None or token_type == "whitespace":
                continue

            if token_type == "name":
                if pending_filter:
                    kind: JinjaSpanKind = "filter"
                elif value in JINJA_KEYWORDS:
                    kind = "keyword"
                else:
                    kind = "variable"
                spans.append(JinjaSpan(start, end, kind, value))
                pending_filter = False
                continue

            if token_type == "operator":
                spans.append(JinjaSpan(start, end, "operator", value))
                pending_filter = value == "|"
                continue

            pending_filter = False
    except TemplateSyntaxError:
        return _fallback_delimiter_spans(masked)

    return spans


def diagnose(text: str) -> JinjaDiagnostics:
    """Parse *text* using the real top-level Jinja2 environment."""
    masked = _mask_inert_regions(text)
    if not _JINJA_MARKER_RE.search(masked):
        return JinjaDiagnostics(has_jinja=False, ok=True)

    env = get_jinja_env()
    try:
        env.parse(masked)
    except TemplateSyntaxError as exc:
        line_starts = _line_start_offsets(text)
        lineno = exc.lineno or 1
        line_start = line_starts[min(max(lineno - 1, 0), len(line_starts) - 1)]
        line_end = text.find("\n", line_start)
        if line_end == -1:
            line_end = len(text)
        message = exc.message or str(exc)
        col, span = _error_location(text, line_start, line_end, message)
        return JinjaDiagnostics(
            has_jinja=True,
            ok=False,
            message=message,
            lineno=lineno,
            col=col,
            span=span,
        )

    return JinjaDiagnostics(has_jinja=True, ok=True)


def inspect_template(
    text: str,
    *,
    known: set[str] | None = None,
) -> JinjaDiagnostics:
    """Return parse diagnostics plus unknown-variable lint for *text*."""
    diagnostics = diagnose(text)
    if not diagnostics.has_jinja or not diagnostics.ok:
        return diagnostics

    known_vars = known_toplevel_context() if known is None else known
    unknown = tuple(sorted(unknown_variables(text, known_vars)))
    if not unknown:
        return diagnostics
    return JinjaDiagnostics(
        has_jinja=diagnostics.has_jinja,
        ok=diagnostics.ok,
        message=diagnostics.message,
        lineno=diagnostics.lineno,
        col=diagnostics.col,
        span=diagnostics.span,
        unknown_variables=unknown,
    )


def unknown_variables(text: str, known: set[str]) -> list[str]:
    """Return undeclared variables that are not in *known*."""
    masked = _mask_inert_regions(text)
    if not _JINJA_MARKER_RE.search(masked):
        return []
    env = get_jinja_env()
    try:
        ast = env.parse(masked)
    except TemplateSyntaxError:
        return []
    return sorted(meta.find_undeclared_variables(ast) - set(known))


def known_toplevel_context() -> set[str]:
    """Return reserved names accepted by top-level prompt tooling."""
    return set(RESERVED_GLOBAL_NAMES)


def builtin_runtime_names() -> set[str]:
    """Return agent-run built-in names accepted by prompt diagnostics."""
    return set(BUILTIN_RUNTIME_NAMES)


def builtin_runtime_member_names(namespace: str) -> set[str]:
    """Return known static member names for an agent-run runtime namespace."""
    return set(RUNTIME_NAMESPACE_MEMBERS.get(namespace, frozenset()))


def jinja_filter_names() -> tuple[str, ...]:
    """Return registered filter names for prompt completion."""
    return tuple(sorted(get_jinja_env().filters))


def completion_context(
    text: str,
    cursor_offset: int,
) -> JinjaCompletionContext | None:
    """Return a Jinja completion context at *cursor_offset*, if any."""
    tag = _tag_at_cursor(text, cursor_offset)
    if tag is None:
        return None
    tag_kind, open_start, open_end, close_start, _close_end = tag
    if tag_kind == "comment":
        return None

    content_start = open_end
    content_end = len(text) if close_start is None else close_start
    cursor_offset = min(max(cursor_offset, content_start), content_end)
    token_start = cursor_offset
    while token_start > content_start and _name_char(text[token_start - 1]):
        token_start -= 1
    token_end = cursor_offset
    while token_end < content_end and _name_char(text[token_end]):
        token_end += 1
    prefix = text[token_start:cursor_offset]
    namespace = _namespace_before_token(text, content_start, token_start)
    return JinjaCompletionContext(
        replacement_start=token_start,
        replacement_end=token_end,
        prefix=prefix,
        tag_kind="block" if tag_kind == "block" else "variable",
        namespace=namespace,
    )


def matching_delimiter_spans(
    text: str,
    cursor_offset: int,
) -> tuple[tuple[int, int], ...]:
    """Return delimiter spans for the tag enclosing *cursor_offset*."""
    tag = _tag_at_cursor(text, cursor_offset)
    if tag is None:
        return ()
    _tag_kind, open_start, open_end, close_start, close_end = tag
    spans = [(open_start, open_end)]
    if close_start is not None and close_end is not None:
        spans.append((close_start, close_end))
    return tuple(spans)


def _mask_jinja_regions(text: str) -> str:
    ranges = code_literal_ranges(text) + _alt_jinja_overlap_ranges(text)
    return _mask_ranges(text, ranges)


def _mask_inert_regions(text: str) -> str:
    ranges = literal_zone_ranges(text) + _alt_jinja_overlap_ranges(text)
    return _mask_ranges(text, ranges)


def _alt_jinja_overlap_ranges(text: str) -> list[tuple[int, int]]:
    """Mask false ``{%`` markers formed by adjacent ``%{`` and ``%id``."""
    ranges: list[tuple[int, int]] = []
    if "%{%" not in text:
        return ranges
    for match in _ALT_DIRECTIVE_RE.finditer(text):
        open_pos = match.end() - 1
        if text[open_pos] == "{" and text[open_pos + 1 : open_pos + 2] == "%":
            ranges.append((open_pos, open_pos + 2))
    return ranges


def _mask_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    if not ranges:
        return text
    chars = list(text)
    for start, end in ranges:
        for idx in range(start, end):
            if chars[idx] not in "\r\n":
                chars[idx] = " "
    return "".join(chars)


def _fallback_delimiter_spans(masked: str) -> list[JinjaSpan]:
    spans: list[JinjaSpan] = []
    for match in re.finditer(r"\{\{|\{%|\{#|\}\}|%\}|#\}", masked):
        spans.append(JinjaSpan(match.start(), match.end(), "delimiter", match.group()))
    return spans


def _line_start_offsets(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


def _error_location(
    text: str,
    line_start: int,
    line_end: int,
    message: str,
) -> tuple[int, tuple[int, int]]:
    line = text[line_start:line_end]
    token_match = re.search(r"unexpected '([^']+)'", message, re.IGNORECASE)
    if token_match is not None:
        token = token_match.group(1)
        token_col = line.find(token)
        if token_col >= 0:
            start = line_start + token_col
            return token_col, (start, min(start + max(1, len(token)), line_end))

    if message.lower().startswith("unexpected end"):
        opener = max(text.rfind("{{", 0, line_end), text.rfind("{%", 0, line_end))
        if opener >= 0:
            return opener - line_start, (opener, min(opener + 2, len(text)))

    candidates = [
        line.rfind(marker)
        for marker in ("{{", "{%", "{#", "}}", "%}", "#}")
        if line.rfind(marker) >= 0
    ]
    col = max(candidates) if candidates else len(line.rstrip("\r\n"))
    start = line_start + col
    return col, (start, min(start + 2, max(start + 1, line_end)))


def _tag_at_cursor(
    text: str,
    cursor_offset: int,
) -> tuple[str, int, int, int | None, int | None] | None:
    masked = _mask_jinja_regions(text)
    cursor_offset = min(max(cursor_offset, 0), len(masked))
    best: tuple[str, int, int, int | None, int | None] | None = None
    for tag_kind, opener, closer in (
        ("variable", "{{", "}}"),
        ("block", "{%", "%}"),
        ("comment", "{#", "#}"),
    ):
        search_start = 0
        while True:
            open_start = masked.find(opener, search_start)
            if open_start == -1 or open_start > cursor_offset:
                break
            open_end = open_start + len(opener)
            raw_close_start = masked.find(closer, open_end)
            close_start = None if raw_close_start == -1 else raw_close_start
            close_end = None if close_start is None else close_start + len(closer)
            inside = cursor_offset >= open_end and (
                close_start is None or cursor_offset <= close_start
            )
            on_delimiter = open_start <= cursor_offset <= open_end or (
                close_start is not None
                and close_end is not None
                and close_start <= cursor_offset <= close_end
            )
            if inside or on_delimiter:
                candidate = (tag_kind, open_start, open_end, close_start, close_end)
                if best is None or open_start > best[1]:
                    best = candidate
            search_start = open_end
    return best


def _name_char(char: str) -> bool:
    return char == "_" or char.isalnum()


def _namespace_before_token(
    text: str,
    content_start: int,
    token_start: int,
) -> str | None:
    if token_start <= content_start or text[token_start - 1] != ".":
        return None
    namespace_end = token_start - 1
    namespace_start = namespace_end
    while namespace_start > content_start and _name_char(text[namespace_start - 1]):
        namespace_start -= 1
    if namespace_start == namespace_end:
        return None
    return text[namespace_start:namespace_end]
