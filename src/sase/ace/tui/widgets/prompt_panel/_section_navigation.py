"""Render-pass section indexing for the Agents metadata panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import ref

from rich.segment import Segment
from textual._context import active_app
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, RichVisual, Visual

if TYPE_CHECKING:
    from . import AgentPromptPanel


SECTION_MARKER_META_KEY = "sase_prompt_panel_section"


@dataclass(frozen=True, slots=True)
class PromptPanelSectionAnchor:
    """One semantic section title and its rendered content row."""

    identity: str
    row: int


class SectionTrackingVisual(Visual):
    """Pass through Textual's normal visual while collecting marked rows."""

    __slots__ = ("_generation", "_owner", "_visual")

    def __init__(
        self,
        visual: Visual,
        owner: AgentPromptPanel,
        generation: int,
    ) -> None:
        self._visual = visual
        self._owner = ref(owner)
        self._generation = generation

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        strips = self._visual.render_strips(width, height, style, options)
        if isinstance(self._visual, RichVisual):
            # Rich anchors are collected from the full measurement stream in
            # get_height(), while this remains the untouched paint path.
            return strips

        anchors: list[PromptPanelSectionAnchor] = []
        seen: set[str] = set()
        for row, strip in enumerate(strips):
            for segment in strip:
                identity = _segment_section_identity(segment)
                if identity is not None and identity not in seen:
                    seen.add(identity)
                    anchors.append(PromptPanelSectionAnchor(identity, row))

        self._publish(width=width, anchors=tuple(anchors))
        return strips

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        """Delegate optimal-width measurement without changing the visual."""
        return self._visual.get_optimal_width(rules, container_width)

    def get_minimal_width(self, rules: RulesMap) -> int:
        """Delegate minimal-width measurement without changing the visual."""
        return self._visual.get_minimal_width(rules)

    def get_height(self, rules: RulesMap, width: int) -> int:
        """Collect Rich anchors during its existing full measurement stream."""
        if not isinstance(self._visual, RichVisual):
            return self._visual.get_height(rules, width)

        app = active_app.get()
        options = app.console_options.update_width(width).update(highlight=False)
        segments = app.console.render(self._visual._renderable, options)  # noqa: SLF001
        anchors: list[PromptPanelSectionAnchor] = []
        seen: set[str] = set()
        row = 0
        for segment in segments:
            identity = _segment_section_identity(segment)
            if identity is not None and identity not in seen:
                seen.add(identity)
                anchors.append(PromptPanelSectionAnchor(identity, row))
            row += segment.text.count("\n")
        self._publish(width=width, anchors=tuple(anchors))
        return row

    def _publish(
        self,
        *,
        width: int,
        anchors: tuple[PromptPanelSectionAnchor, ...],
    ) -> None:
        """Publish a complete anchor set if the owning panel still exists."""
        owner = self._owner()
        if owner is not None:
            owner._publish_section_layout(  # noqa: SLF001
                generation=self._generation,
                width=width,
                anchors=anchors,
            )


def _segment_section_identity(segment: Segment) -> str | None:
    style = segment.style
    if style is None or not style.meta:
        return None
    identity = style.meta.get(SECTION_MARKER_META_KEY)
    return identity if isinstance(identity, str) and identity else None


__all__ = [
    "PromptPanelSectionAnchor",
    "SECTION_MARKER_META_KEY",
    "SectionTrackingVisual",
]
