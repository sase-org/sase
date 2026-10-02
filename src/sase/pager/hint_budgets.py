"""Textual-free content caps shared by the pager link scanner.

Moved out of :mod:`sase.ace.tui.util.lazy_syntax` (the plain-text truncation
pieces) and :mod:`sase.ace.tui.widgets.prompt_panel._hint_caps` (the hint
budget pieces) so the cold path can bound scan input without importing the TUI
stack. The original modules re-export every name here, so ACE callers and
behavior are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from rich.text import Text

from sase.pager.path_hints import (
    FileHintMatcher,
    file_hint_match_span,
    iter_file_path_matches,
)

# Keep the pathological plain-text path within the module's sub-100 ms budget.
# The byte cap protects byte-heavy content with relatively few very long lines;
# the line cap protects content made up of many short lines.
PLAIN_RENDER_MAX_BYTES = 128_000
PLAIN_RENDER_MAX_LINES = 5_000

HINT_TRUNCATION_STYLE = "dim italic #87D7FF"
HINT_TRUNCATION_MESSAGE = "hints not generated past this point"

# Canonical value lives in ``sase.sdd.plan_refs.PLAN_REFERENCE_PREFIX``; it is
# inlined here (rather than imported) so this leaf stays off the SDD store
# chain. ``test_pager_cold_path_import_cost`` asserts the two stay equal.
_LOGICAL_PLAN_REFERENCE_PREFIX = "plan:"
_PARTIAL_LOGICAL_PLAN_REFERENCE_RE = re.compile(
    rf"(?<![/\w@.])@?{re.escape(_LOGICAL_PLAN_REFERENCE_PREFIX)}[\w.+\-/]*$"
)


@dataclass
class HintContentBudget:
    """Remaining scan budget shared by all body fragments in one render."""

    remaining_bytes: int = PLAIN_RENDER_MAX_BYTES
    remaining_lines: int = PLAIN_RENDER_MAX_LINES


@dataclass(frozen=True)
class _BoundedHintContent:
    """A bounded prefix to scan plus its optional user-visible notice."""

    content: str
    notice: Text | None


def _line_count(content: str) -> int:
    """Return the logical line count used by capped plain rendering."""
    return content.count("\n") + (1 if not content.endswith("\n") else 0)


def _utf8_prefix(content: str, max_bytes: int) -> str:
    """Return the longest safe UTF-8 prefix within ``max_bytes``."""
    encoded = content.encode("utf-8", errors="replace")
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def truncate_plain_content(
    content: str,
    *,
    max_lines: int,
    max_bytes: int = PLAIN_RENDER_MAX_BYTES,
) -> tuple[str, int, int, bool, bool]:
    """Return a bounded head prefix and details about what was elided."""
    total_lines = _line_count(content)
    total_bytes = len(content.encode("utf-8", errors="replace"))
    line_truncated = total_lines > max_lines

    rendered_lines: list[str] = []
    rendered_bytes = 0
    byte_truncated = False
    line_start = 0
    for _ in range(max_lines):
        if line_start >= len(content):
            break
        newline = content.find("\n", line_start)
        line_end = len(content) if newline == -1 else newline + 1
        line = content[line_start:line_end]
        line_bytes = len(line.encode("utf-8", errors="replace"))
        if rendered_bytes + line_bytes <= max_bytes:
            rendered_lines.append(line)
            rendered_bytes += line_bytes
            line_start = line_end
            continue

        byte_truncated = True
        if not rendered_lines and max_bytes > 0:
            rendered_lines.append(_utf8_prefix(line, max_bytes))
        break

    rendered_content = "".join(rendered_lines)
    truncated = line_truncated or byte_truncated
    if truncated:
        rendered_content = rendered_content.removesuffix("\n").removesuffix("\r")

    remaining_lines = max(0, total_lines - _line_count(rendered_content))
    remaining_bytes = max(
        0,
        total_bytes - len(rendered_content.encode("utf-8", errors="replace")),
    )
    return (
        rendered_content,
        remaining_lines,
        remaining_bytes,
        line_truncated,
        byte_truncated,
    )


def _format_approx_bytes(byte_count: int) -> str:
    if byte_count < 1_024:
        return f"{byte_count} B"
    if byte_count < 1_024 * 1_024:
        return f"{byte_count / 1_024:.1f} KiB"
    return f"{byte_count / (1_024 * 1_024):.1f} MiB"


def _drop_partial_trailing_path(
    content: str,
    source: str,
    *,
    matcher: FileHintMatcher = iter_file_path_matches,
) -> str:
    """Do not turn a byte-truncated path prefix into a different hint."""
    if not content or len(content) >= len(source):
        return content
    match = None
    for candidate in matcher(content):
        match = candidate
    if match is not None and match.end(2) == len(content):
        if not _path_continues_after_truncation(source, len(content)):
            return content
        start, _end = file_hint_match_span(match)
        return content[:start]
    partial_logical = _PARTIAL_LOGICAL_PLAN_REFERENCE_RE.search(content)
    if partial_logical is None or not _path_continues_after_truncation(
        source,
        len(content),
    ):
        return content
    return content[: partial_logical.start()]


def _path_continues_after_truncation(source: str, offset: int) -> bool:
    char = source[offset]
    return char in "._+-/" or char.isalnum()


def bound_hint_content(
    content: str,
    *,
    budget: HintContentBudget | None = None,
    matcher: FileHintMatcher = iter_file_path_matches,
) -> _BoundedHintContent:
    """Bound one visible fragment before regex scanning and hint insertion."""
    max_bytes = (
        PLAIN_RENDER_MAX_BYTES
        if budget is None
        else max(0, min(PLAIN_RENDER_MAX_BYTES, budget.remaining_bytes))
    )
    max_lines = (
        PLAIN_RENDER_MAX_LINES
        if budget is None
        else max(0, min(PLAIN_RENDER_MAX_LINES, budget.remaining_lines))
    )
    (
        bounded,
        remaining_lines,
        remaining_bytes,
        line_truncated,
        byte_truncated,
    ) = truncate_plain_content(
        content,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )
    if byte_truncated:
        bounded = _drop_partial_trailing_path(
            bounded,
            content,
            matcher=matcher,
        )

    if budget is not None:
        budget.remaining_bytes = max(
            0,
            budget.remaining_bytes - len(bounded.encode("utf-8", errors="replace")),
        )
        consumed_lines = bounded.count("\n") + (
            1 if bounded and not bounded.endswith("\n") else 0
        )
        budget.remaining_lines = max(0, budget.remaining_lines - consumed_lines)

    if not line_truncated and not byte_truncated:
        return _BoundedHintContent(content=bounded, notice=None)

    omitted: list[str] = []
    if line_truncated and remaining_lines:
        omitted.append(f"{remaining_lines} more lines")
    if byte_truncated and remaining_bytes:
        omitted.append(f"approximately {_format_approx_bytes(remaining_bytes)} omitted")
    detail = " and ".join(omitted) or "more content"
    return _BoundedHintContent(
        content=bounded,
        notice=Text(
            f"\n… {detail} — {HINT_TRUNCATION_MESSAGE}",
            style=HINT_TRUNCATION_STYLE,
        ),
    )


__all__ = [
    "HINT_TRUNCATION_MESSAGE",
    "HINT_TRUNCATION_STYLE",
    "HintContentBudget",
    "PLAIN_RENDER_MAX_BYTES",
    "PLAIN_RENDER_MAX_LINES",
    "bound_hint_content",
    "truncate_plain_content",
]
