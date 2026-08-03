"""Span-preserving file hints for synthetic container text."""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text

from ._agent_display_state import HeaderHintState
from ._file_path_hints import (
    FileHintPathResolver,
    LOGICAL_PLAN_REFERENCE_PREFIX,
    append_text_with_file_hints,
    file_hint_match_span,
    iter_container_file_path_matches,
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
    bounded = bound_hint_content(
        source.plain,
        budget=budget,
        matcher=iter_container_file_path_matches,
    )
    source_text = bounded.content
    counter = hint_state.hint_counter
    insertions = tuple(
        (
            file_hint_match_span(match)[0],
            len(f"[{counter + index}] "),
        )
        for index, match in enumerate(iter_container_file_path_matches(source_text))
    )
    text = Text(style=source.style)
    hint_state.hint_counter = append_text_with_file_hints(
        text,
        source_text,
        hint_state.hint_counter,
        hint_state.hint_mappings,
        workspace_dir,
        path_resolver=path_resolver or container_hint_path_resolver({}),
        matcher=iter_container_file_path_matches,
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
) -> FileHintPathResolver:
    """Prefer worker-resolved container aliases, then use normal fallback."""

    def resolve(path: str, workspace_dir: str | None) -> str:
        normalized_path = _normalize_hint_token(path)
        stripped_path = _strip_logical_plan_prefix(path)
        normalized_stripped_path = _normalize_hint_token(stripped_path)
        for token in (
            path,
            normalized_path,
            stripped_path,
            normalized_stripped_path,
        ):
            if not token:
                continue
            exact = hint_paths.get(token)
            if exact is not None:
                return exact

        best_match: tuple[int, str] | None = None
        suffix_path = normalized_stripped_path or normalized_path
        for token, target in hint_paths.items():
            normalized_token = _normalize_hint_token(token)
            if not normalized_token:
                continue
            if not normalized_token.endswith(f"/{suffix_path}"):
                continue
            candidate = (len(normalized_token), target)
            if best_match is None or candidate[0] > best_match[0]:
                best_match = candidate
        if best_match is not None:
            return best_match[1]
        return resolve_file_path(stripped_path, workspace_dir)

    return resolve


def _normalize_hint_token(value: str) -> str:
    return value.strip().lstrip("@").removeprefix("./").rstrip("/")


def _strip_logical_plan_prefix(value: str) -> str:
    return value.strip().lstrip("@").removeprefix(LOGICAL_PLAN_REFERENCE_PREFIX)


__all__ = ["container_hint_path_resolver", "container_text_with_file_hints"]
