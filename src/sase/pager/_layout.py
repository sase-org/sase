"""Width-cached body composition for the pager's virtualized content.

The pager renders every section into one Rich renderable painted by a single
``Static`` (Textual's compositor virtualizes which rows actually draw — see
``AgentFilePanel``/``AgentPromptPanel`` for the same "one big renderable, no
per-line widgets" shape). This module only computes *what* to paint and
*where* each section starts, at a given width; callers own the caching (the
Textual layer rebuilds only when the body's actual width changes, per
``tui_perf`` rule 8).
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console, Group, RenderableType

from sase.pager._chrome import section_rule
from sase.pager._labels import PagerLabelLayer, render_section_with_labels
from sase.pager.document import PagerDocument, PagerSection

_DIVIDER_LINES = 1


@dataclass(frozen=True, slots=True)
class ComposedBody:
    """One document rendered at a fixed width."""

    renderable: RenderableType
    section_offsets: tuple[int, ...]
    total_height: int


def _measure_section_heights(
    sections: tuple[PagerSection, ...],
    width: int,
    *,
    label_layer: PagerLabelLayer | None = None,
    pending_prefix: str = "",
) -> tuple[int, ...]:
    """Return each section's wrapped line count at ``width``, no I/O."""
    console = Console(width=max(width, 1), color_system=None, highlight=False)
    heights = []
    for index, section in enumerate(sections):
        lines = console.render_lines(
            _section_renderable(
                section,
                section_index=index,
                label_layer=label_layer,
                pending_prefix=pending_prefix,
            ),
            pad=False,
        )
        heights.append(max(len(lines), 1))
    return tuple(heights)


def _section_row_offsets(heights: tuple[int, ...]) -> tuple[int, ...]:
    """Return the row where each section's own rule (or the top) sits.

    Section 0 has no leading rule — the chrome band already identifies the
    document — so its offset is row 0. Every later section's offset is the
    row its transition rule occupies, which is exactly the row
    ``ctrl+n``/``ctrl+p`` scroll to (design doc section D5).
    """
    if not heights:
        return (0,)
    offsets = [0]
    row = heights[0]
    for height in heights[1:]:
        offsets.append(row)
        row += _DIVIDER_LINES + height
    return tuple(offsets)


def compose_body(
    document: PagerDocument,
    width: int,
    *,
    label_layer: PagerLabelLayer | None = None,
    pending_prefix: str = "",
) -> ComposedBody:
    """Render *document* at ``width``: section bodies plus transition rules."""
    sections = document.sections
    if not sections:
        return ComposedBody(renderable=Group(), section_offsets=(0,), total_height=0)

    heights = _measure_section_heights(
        sections,
        width,
        label_layer=label_layer,
        pending_prefix=pending_prefix,
    )
    offsets = _section_row_offsets(heights)
    total = len(sections)

    parts: list[RenderableType] = []
    for index, section in enumerate(sections):
        if index > 0:
            parts.append(
                section_rule(section, index=index + 1, total=total, width=width)
            )
        parts.append(
            _section_renderable(
                section,
                section_index=index,
                label_layer=label_layer,
                pending_prefix=pending_prefix,
            )
        )

    total_height = offsets[-1] + heights[-1]
    return ComposedBody(
        renderable=Group(*parts),
        section_offsets=offsets,
        total_height=total_height,
    )


def current_section_index(offsets: tuple[int, ...], scroll_y: int) -> int:
    """Return the index of the section whose rule is at or above ``scroll_y``."""
    index = 0
    for candidate, offset in enumerate(offsets):
        if offset <= scroll_y:
            index = candidate
        else:
            break
    return index


def search_corpus(document: PagerDocument) -> str:
    """Return one logical-line-aligned corpus for the re-hosted vim search.

    Search renders unwrapped (design doc section D9's prior art always
    disables wrapping for the overlay), so a logical line here is exactly
    one visible row — unlike the wrapped body used outside search, whose
    row count depends on width.
    """
    sections = document.sections
    if not sections:
        return ""
    parts: list[str] = []
    total = len(sections)
    for index, section in enumerate(sections):
        if index > 0:
            parts.append(f"── {index + 1}/{total} · {section.title} ──\n")
        text = section.plain_text
        parts.append(text if text.endswith("\n") else f"{text}\n")
    return "".join(parts)


def _section_renderable(
    section: PagerSection,
    *,
    section_index: int,
    label_layer: PagerLabelLayer | None,
    pending_prefix: str,
) -> RenderableType:
    if label_layer is None:
        return section.body_renderable
    labels = label_layer.labels_by_section[section_index]
    if not labels:
        return section.body_renderable
    return render_section_with_labels(
        section,
        labels,
        pending_prefix=pending_prefix,
    )


__all__ = [
    "ComposedBody",
    "compose_body",
    "current_section_index",
    "render_section_with_labels",
    "search_corpus",
]
