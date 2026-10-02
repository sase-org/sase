"""Shared content caps for file-hint generation."""

from __future__ import annotations

from typing import Protocol

from rich.style import StyleType
from rich.text import Text

from sase.pager.hint_budgets import (
    HINT_TRUNCATION_MESSAGE,
    HINT_TRUNCATION_STYLE,
    HintContentBudget,
    bound_hint_content,
)

from ._file_path_hints import (
    FileHintMatcher,
    append_text_with_file_hints,
    iter_file_path_matches,
)

__all__ = [
    "HINT_TRUNCATION_MESSAGE",
    "HINT_TRUNCATION_STYLE",
    "HintContentBudget",
    "_AppendableText",
    "append_bounded_text_with_file_hints",
    "bound_hint_content",
]


class _AppendableText(Protocol):
    """Minimal Rich text target accepted by the hint appender."""

    def append(
        self,
        text: str | Text,
        style: StyleType | None = None,
    ) -> object: ...


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
