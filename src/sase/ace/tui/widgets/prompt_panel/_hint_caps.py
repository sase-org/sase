"""Shared content caps for file-hint generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from rich.style import StyleType
from rich.text import Text

from ...util.lazy_syntax import (
    PLAIN_RENDER_MAX_BYTES,
    PLAIN_RENDER_MAX_LINES,
    truncate_plain_content,
)
from ._file_path_hints import (
    FileHintMatcher,
    LOGICAL_PLAN_REFERENCE_PREFIX,
    append_text_with_file_hints,
    file_hint_match_span,
    iter_file_path_matches,
)

HINT_TRUNCATION_STYLE = "dim italic #87D7FF"
HINT_TRUNCATION_MESSAGE = "hints not generated past this point"
_PARTIAL_LOGICAL_PLAN_REFERENCE_RE = re.compile(
    rf"(?<![/\w@.])@?{re.escape(LOGICAL_PLAN_REFERENCE_PREFIX)}[\w.+\-/]*$"
)


class _AppendableText(Protocol):
    """Minimal Rich text target accepted by the hint appender."""

    def append(
        self,
        text: str | Text,
        style: StyleType | None = None,
    ) -> object: ...


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


def append_bounded_text_with_file_hints(
    text: _AppendableText,
    content: str,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    style: str = "",
    *,
    budget: HintContentBudget | None = None,
    matcher: FileHintMatcher = iter_file_path_matches,
) -> int:
    """Append a capped, annotated prefix and an explicit truncation notice."""
    bounded = bound_hint_content(content, budget=budget, matcher=matcher)
    hint_counter = append_text_with_file_hints(
        text,
        bounded.content,
        hint_counter,
        hint_mappings,
        workspace_dir,
        style,
        matcher=matcher,
    )
    if bounded.notice is not None:
        text.append(bounded.notice)
    return hint_counter
