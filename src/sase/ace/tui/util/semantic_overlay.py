"""Fail-open glossary and repo-mention overlays for Rich prompt text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from rich.style import StyleType

from sase.ace.tui.util.editor_offsets import editor_range_to_offsets
from sase.ace.tui.util.lazy_syntax import (
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES,
)
from sase.ace.tui.util.semantic_styles import SemanticHighlightStyles
from sase.core.glossary_facade import scan_glossary_spans
from sase.xprompt import alt_inspect, xprompt_inspect
from sase.xprompt._literal_zones import code_literal_ranges
from sase.xprompt.glossary_catalog import EditorGlossaryCatalog
from sase.xprompt.repo_mention_catalog import (
    EditorRepoMentionCatalog,
    scan_repo_mentions,
)


class _StylizableText(Protocol):
    def stylize(
        self,
        style: StyleType,
        start: int = 0,
        end: int | None = None,
    ) -> None: ...


def apply_semantic_overlays(
    highlighted: _StylizableText,
    source: str,
    *,
    glossary_catalog: EditorGlossaryCatalog | None = None,
    repo_catalog: EditorRepoMentionCatalog | None = None,
    styles: SemanticHighlightStyles | None = None,
    region_start: int = 0,
    skip_xprompt: bool = False,
    known_skills: frozenset[str] = frozenset(),
) -> None:
    """Apply glossary then repo styles to natural-language spans in *source*.

    Scanning and range conversion finish before the target is mutated so a
    malformed catalog or span cannot leave a partial overlay. Inline and
    fenced code interiors are skipped. When *skip_xprompt* is true, structural
    xprompt tokens are also skipped so later xprompt styles win cleanly.
    Oversized regions are left untouched.
    """
    if styles is None:
        return
    if glossary_catalog is None and repo_catalog is None:
        return
    if _exceeds_semantic_cap(source):
        return

    try:
        protected = _protected_ranges(
            source,
            skip_xprompt=skip_xprompt,
            known_skills=known_skills,
        )
        overlays = _semantic_overlay_spans(
            source,
            glossary_catalog=glossary_catalog,
            repo_catalog=repo_catalog,
            styles=styles,
            protected=protected,
        )
    except Exception:
        return

    for style, start, end in overlays:
        highlighted.stylize(
            style,
            region_start + start,
            region_start + end,
        )


def _exceeds_semantic_cap(source: str) -> bool:
    return (
        len(source.encode("utf-8", errors="replace"))
        > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
        or source.count("\n") > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES
    )


def _protected_ranges(
    source: str,
    *,
    skip_xprompt: bool,
    known_skills: frozenset[str],
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    if "`" in source or "~~~" in source or "```" in source:
        ranges.extend(code_literal_ranges(source))
    if skip_xprompt:
        ranges.extend(
            (span.start, span.end)
            for span in xprompt_inspect.tokenize(source, known_skills=known_skills)
        )
        ranges.extend((span.start, span.end) for span in alt_inspect.tokenize(source))
    return ranges


def _semantic_overlay_spans(
    source: str,
    *,
    glossary_catalog: EditorGlossaryCatalog | None,
    repo_catalog: EditorRepoMentionCatalog | None,
    styles: SemanticHighlightStyles,
    protected: Sequence[tuple[int, int]],
) -> list[tuple[StyleType, int, int]]:
    overlays: list[tuple[StyleType, int, int]] = []
    if repo_catalog is not None:
        overlays.extend(
            (styles.repo, start, end)
            for start, end in _catalog_segment_offsets(
                source,
                (span.segments for span in scan_repo_mentions(repo_catalog, source)),
                protected,
            )
        )
    if glossary_catalog is not None:
        overlays.extend(
            (styles.glossary, start, end)
            for start, end in _catalog_segment_offsets(
                source,
                (
                    span.segments
                    for span in scan_glossary_spans(glossary_catalog.compiled, source)
                ),
                protected,
            )
        )
    return overlays


def _catalog_segment_offsets(
    source: str,
    segment_groups: Any,
    protected: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    offsets: list[tuple[int, int]] = []
    for segments in segment_groups:
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            converted = editor_range_to_offsets(source, segment.get("range"))
            if converted is None:
                continue
            start, end = converted
            if _overlaps(start, end, protected):
                continue
            offsets.append((start, end))
    return offsets


def _overlaps(
    start: int,
    end: int,
    ranges: Sequence[tuple[int, int]],
) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


__all__ = [
    "apply_semantic_overlays",
]
