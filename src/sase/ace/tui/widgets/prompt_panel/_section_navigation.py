"""Render-pass section indexing for the Agents metadata panel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
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
SECTION_FOLD_ONLY_META_KEY = "sase_prompt_panel_section_fold_only"


class PromptPanelSectionRole(Enum):
    """Whether a marked span is a navigable title or only a fold anchor."""

    TITLE = auto()
    FOLD_ONLY = auto()


@dataclass(frozen=True, slots=True)
class PromptPanelSectionAnchor:
    """One semantic section title and its rendered content row."""

    identity: str
    row: int
    role: PromptPanelSectionRole = PromptPanelSectionRole.TITLE


class PromptPanelSectionTargetKind(Enum):
    """Resolution states for one metadata-section navigation request."""

    NOT_READY = auto()
    EMPTY = auto()
    TOP = auto()
    ANCHOR = auto()


@dataclass(frozen=True, slots=True)
class PromptPanelSectionTarget:
    """A cached navigation result without overloading a missing anchor."""

    kind: PromptPanelSectionTargetKind
    anchor: PromptPanelSectionAnchor | None = None

    @property
    def ready(self) -> bool:
        """Whether the current generation and width have published anchors."""
        return self.kind is not PromptPanelSectionTargetKind.NOT_READY


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
                resolved = _segment_section_identity(segment)
                if resolved is None:
                    continue
                identity, role = resolved
                if identity not in seen:
                    seen.add(identity)
                    anchors.append(PromptPanelSectionAnchor(identity, row, role))

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
            resolved = _segment_section_identity(segment)
            if resolved is not None:
                identity, role = resolved
                if identity not in seen:
                    seen.add(identity)
                    anchors.append(PromptPanelSectionAnchor(identity, row, role))
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


def _segment_section_identity(
    segment: Segment,
) -> tuple[str, PromptPanelSectionRole] | None:
    style = segment.style
    meta = style.meta if style is not None else None
    if not meta:
        return None
    identity = meta.get(SECTION_MARKER_META_KEY)
    if not isinstance(identity, str) or not identity:
        return None
    role = (
        PromptPanelSectionRole.FOLD_ONLY
        if meta.get(SECTION_FOLD_ONLY_META_KEY)
        else PromptPanelSectionRole.TITLE
    )
    return identity, role


__all__ = [
    "PromptPanelSectionAnchor",
    "PromptPanelSectionRole",
    "PromptPanelSectionTarget",
    "PromptPanelSectionTargetKind",
    "SECTION_FOLD_ONLY_META_KEY",
    "SECTION_MARKER_META_KEY",
    "SectionTrackingVisual",
]
