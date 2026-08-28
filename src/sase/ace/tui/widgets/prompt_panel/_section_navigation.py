"""Render-pass section indexing for the Agents metadata panel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, cast
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

    __slots__ = ("_anchors_by_key", "_generation", "_owner", "_visual")

    def __init__(
        self,
        visual: Visual,
        owner: AgentPromptPanel,
        generation: int,
    ) -> None:
        self._visual = visual
        self._owner = ref(owner)
        self._generation = generation
        self._anchors_by_key: dict[
            tuple[int, int],
            tuple[PromptPanelSectionAnchor, ...],
        ] = {}

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        strips = self._visual.render_strips(width, height, style, options)
        anchors = (
            self._anchors_for_rich_visual(width)
            if isinstance(self._visual, RichVisual)
            else self._anchors_for_strips(width=width, strips=strips)
        )
        self._publish(width=width, anchors=anchors)
        return strips

    def _anchors_for_strips(
        self,
        *,
        width: int,
        strips: list[Strip],
    ) -> tuple[PromptPanelSectionAnchor, ...]:
        """Return cached anchors, collecting them from the paint strips once."""
        key = (self._generation, width)
        cached = self._anchors_by_key.get(key)
        if cached is not None:
            return cached
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

        cached = tuple(anchors)
        self._anchors_by_key[key] = cached
        return cached

    def _anchors_for_rich_visual(
        self,
        width: int,
    ) -> tuple[PromptPanelSectionAnchor, ...]:
        """Return cached Rich anchors from the uncropped segment stream."""
        key = (self._generation, width)
        cached = self._anchors_by_key.get(key)
        if cached is not None:
            return cached

        app = active_app.get()
        options = app.console_options.update_width(width).update(highlight=False)
        renderable = cast(Any, self._visual)._renderable  # noqa: SLF001
        segments = app.console.render(renderable, options)
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

        cached = tuple(anchors)
        self._anchors_by_key[key] = cached
        return cached

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        """Delegate optimal-width measurement without changing the visual."""
        return self._visual.get_optimal_width(rules, container_width)

    def get_minimal_width(self, rules: RulesMap) -> int:
        """Delegate minimal-width measurement without changing the visual."""
        return self._visual.get_minimal_width(rules)

    def get_height(self, rules: RulesMap, width: int) -> int:
        """Delegate height measurement and publish cached Rich anchors."""
        height = self._visual.get_height(rules, width)
        if isinstance(self._visual, RichVisual):
            self._publish(width=width, anchors=self._anchors_for_rich_visual(width))
        return height

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
