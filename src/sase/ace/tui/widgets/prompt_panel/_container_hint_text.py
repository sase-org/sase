"""Span-preserving file hints for synthetic container text."""

from __future__ import annotations

from rich.text import Text

from ._agent_display_state import HeaderHintState
from ._file_path_hints import FILE_PATH_RE, append_text_with_file_hints
from ._hint_caps import HintContentBudget, bound_hint_content


def container_text_with_file_hints(
    content: str | Text,
    hint_state: HeaderHintState,
    *,
    workspace_dir: str | None,
    budget: HintContentBudget | None,
) -> Text:
    """Return bounded text annotated with hints while preserving source spans."""
    source = content if isinstance(content, Text) else Text(content)
    bounded = bound_hint_content(source.plain, budget=budget)
    source_text = bounded.content
    counter = hint_state.hint_counter
    insertions = tuple(
        (
            match.start(1) if match.group(1) else match.start(2),
            len(f"[{counter + index}] "),
        )
        for index, match in enumerate(FILE_PATH_RE.finditer(source_text))
    )
    text = Text(style=source.style)
    hint_state.hint_counter = append_text_with_file_hints(
        text,
        source_text,
        hint_state.hint_counter,
        hint_state.hint_mappings,
        workspace_dir,
    )
    for span in source.spans:
        if span.start >= len(source_text):
            continue
        span_end = min(span.end, len(source_text))
        start = span.start + sum(
            width for position, width in insertions if position <= span.start
        )
        end = span_end + sum(
            width for position, width in insertions if position < span_end
        )
        text.stylize(span.style, start, end)
    if bounded.notice is not None:
        text.append_text(bounded.notice)
    return text


__all__ = ["container_text_with_file_hints"]
