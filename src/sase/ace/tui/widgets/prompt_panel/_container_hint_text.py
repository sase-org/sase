"""Span-preserving file hints for synthetic container text."""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text

from ._agent_display_state import HeaderHintState
from ._file_path_hints import (
    FILE_PATH_RE,
    FileHintPathResolver,
    append_text_with_file_hints,
    resolve_file_path,
)
from ._hint_caps import HintContentBudget, bound_hint_content


def container_text_with_file_hints(
    content: str | Text,
    hint_state: HeaderHintState,
    *,
    workspace_dir: str | None,
    budget: HintContentBudget | None,
    path_resolver: FileHintPathResolver | None = None,
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
        path_resolver=path_resolver,
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


def container_hint_path_resolver(
    hint_paths: Mapping[str, str],
) -> FileHintPathResolver | None:
    """Prefer worker-resolved container aliases, then use normal fallback."""
    if not hint_paths:
        return None

    def resolve(path: str, workspace_dir: str | None) -> str:
        normalized_path = _normalize_hint_token(path)
        exact = hint_paths.get(path) or hint_paths.get(normalized_path)
        if exact is not None:
            return exact

        best_match: tuple[int, str] | None = None
        for token, target in hint_paths.items():
            normalized_token = _normalize_hint_token(token)
            if not normalized_token:
                continue
            if not (
                normalized_token.endswith(f"/{normalized_path}")
                or normalized_path.endswith(f"/{normalized_token}")
            ):
                continue
            candidate = (len(normalized_token), target)
            if best_match is None or candidate[0] > best_match[0]:
                best_match = candidate
        if best_match is not None:
            return best_match[1]
        return resolve_file_path(path, workspace_dir)

    return resolve


def _normalize_hint_token(value: str) -> str:
    return value.strip().lstrip("@").removeprefix("./").rstrip("/")


__all__ = ["container_hint_path_resolver", "container_text_with_file_hints"]
