"""Agent prompt panel widget for the ace TUI."""

from typing import Any

from textual.geometry import Size
from textual.timer import Timer
from textual.widgets import Static

from ...models.agent import Agent
from ...tools import supports_slow_tool_sources
from ...tools.cache import slow_tool_sources_have_pending
from ._agent_display import AgentDisplayMixin
from ._agent_display_hints import AgentHintsDisplayMixin
from ._helpers import (
    aggregate_meta_fields,
    extract_meta_fields,
    format_meta_key,
    load_xprompts_used,
)
from ._section_navigation import (
    PromptPanelSectionAnchor,
    PromptPanelSectionRole,
    PromptPanelSectionTarget,
    PromptPanelSectionTargetKind,
    SectionTrackingVisual,
)
from ._workflow_display import WorkflowDisplayMixin

_SLOW_TOOL_RENDER_TICK_SECONDS = 5.0


class AgentPromptPanel(
    AgentDisplayMixin, AgentHintsDisplayMixin, WorkflowDisplayMixin, Static
):
    """Top panel showing agent details and the input prompt."""

    _slow_tool_render_timer: Timer | None = None
    _slow_tool_tick_agent: Agent | None = None
    _section_generation: int = 0
    _section_anchor_generation: int = -1
    _section_anchor_width: int = -1
    _section_anchors: tuple[PromptPanelSectionAnchor, ...] = ()
    _active_section_identity: str | None = None
    _pending_section_direction: int | None = None
    _section_document_identity: object
    _section_real_content_height: int = 0
    _section_layout_reserve: int = 0
    _section_layout_reserve_enabled: bool = False
    _preserve_missing_section_next_update: bool = False
    _preserve_missing_section_generation: int = -1

    def prepare_section_document(self, identity: object) -> None:
        """Set the logical metadata-document identity for cursor reconciliation."""
        previous = getattr(self, "_section_document_identity", _UNSET)
        if previous != identity:
            self._active_section_identity = None
            self._pending_section_direction = None
            self._section_layout_reserve_enabled = False
        self._section_document_identity = identity

    def prepare_section_document_for_agent(self, agent: Agent) -> None:
        """Select the regular or attempt-pinned document for ``agent``."""
        self.prepare_section_document(
            (agent.identity, getattr(self, "attempt_pinned_number", None))
        )

    def reset_section_document(self) -> None:
        """Reset section state for an empty metadata panel."""
        self.prepare_section_document((_EMPTY_DOCUMENT, id(self)))

    def preserve_missing_section_on_next_update(self) -> None:
        """Keep the cursor through one deliberately incomplete cheap paint."""
        self._preserve_missing_section_next_update = True

    def update(self, content: Any = "", *, layout: bool = True) -> None:
        """Update content while invalidating only the cached rendered anchors."""
        self._section_generation = getattr(self, "_section_generation", 0) + 1
        self._preserve_missing_section_generation = (
            self._section_generation
            if self._preserve_missing_section_next_update
            else -1
        )
        self._preserve_missing_section_next_update = False
        self._section_anchor_generation = -1
        self._section_anchor_width = -1
        self._section_anchors = ()
        super().update(content, layout=layout)

    def render(self) -> SectionTrackingVisual:
        """Render original content through the lightweight section tracker."""
        return SectionTrackingVisual(
            self.visual,
            self,
            getattr(self, "_section_generation", 0),
        )

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        """Reserve enough non-document layout to top-align the final title."""
        real_height = super().get_content_height(container, viewport, width)
        self._section_real_content_height = real_height
        anchors = (
            self._section_anchors
            if self._section_anchor_generation == self._section_generation
            and self._section_anchor_width == width
            else ()
        )
        reserve = 0
        title_anchors = [
            anchor for anchor in anchors if anchor.role is PromptPanelSectionRole.TITLE
        ]
        if (
            getattr(self, "_section_layout_reserve_enabled", False)
            and getattr(self, "id", None) == "agent-prompt-panel"
            and title_anchors
        ):
            reserve = max(0, title_anchors[-1].row + container.height - real_height)
        self._section_layout_reserve = reserve
        return real_height + reserve

    def enable_section_layout_reserve(self) -> bool:
        """Enable final-title alignment extent on the first navigation request."""
        if getattr(self, "id", None) != "agent-prompt-panel" or getattr(
            self, "_section_layout_reserve_enabled", False
        ):
            return False
        self._section_layout_reserve_enabled = True
        self.refresh(layout=True)
        return True

    def _publish_section_layout(
        self,
        *,
        generation: int,
        width: int,
        anchors: tuple[PromptPanelSectionAnchor, ...],
    ) -> None:
        """Publish anchors produced by the current content generation."""
        if generation != getattr(self, "_section_generation", 0):
            return
        self._section_anchor_generation = generation
        self._section_anchor_width = width
        self._section_anchors = anchors
        active = getattr(self, "_active_section_identity", None)
        if (
            active is not None
            and generation != self._preserve_missing_section_generation
            and all(
                anchor.identity != active
                for anchor in anchors
                if anchor.role is PromptPanelSectionRole.TITLE
            )
        ):
            self._active_section_identity = None

    def resolve_section_target(
        self,
        direction: int,
        *,
        width: int,
    ) -> PromptPanelSectionTarget:
        """Resolve an initial or adjacent section from the current render cache.

        The result distinguishes a rendered anchor, the document-top waypoint,
        a valid zero-section document, and the brief invalidation window before
        the refreshed Rich render publishes its anchors.
        """
        generation = getattr(self, "_section_generation", 0)
        ready = (
            getattr(self, "_section_anchor_generation", -1) == generation
            and getattr(self, "_section_anchor_width", -1) == width
        )
        if not ready:
            return PromptPanelSectionTarget(PromptPanelSectionTargetKind.NOT_READY)

        all_anchors: tuple[PromptPanelSectionAnchor, ...] = getattr(
            self, "_section_anchors", ()
        )
        anchors = tuple(
            anchor
            for anchor in all_anchors
            if anchor.role is PromptPanelSectionRole.TITLE
        )
        if not anchors:
            return PromptPanelSectionTarget(PromptPanelSectionTargetKind.EMPTY)

        active = getattr(self, "_active_section_identity", None)
        if active is None:
            index = 0 if direction > 0 else len(anchors) - 1
        else:
            index_by_identity = {
                anchor.identity: index for index, anchor in enumerate(anchors)
            }
            current_index = index_by_identity.get(active)
            if current_index is None:
                index = 0 if direction > 0 else len(anchors) - 1
            elif (direction > 0 and current_index == len(anchors) - 1) or (
                direction < 0 and current_index == 0
            ):
                self._active_section_identity = None
                return PromptPanelSectionTarget(PromptPanelSectionTargetKind.TOP)
            else:
                index = (current_index + direction) % len(anchors)

        target = anchors[index]
        self._active_section_identity = target.identity
        return PromptPanelSectionTarget(
            PromptPanelSectionTargetKind.ANCHOR,
            target,
        )

    def resolve_section_at_row(self, row: int, *, width: int) -> str | None:
        """Resolve the section occupying ``row`` from the current anchor cache.

        ``None`` means either that the current render has not published its
        anchors yet or that the row is above the first marked section.  Fold
        actions use this distinction to no-op during layout invalidation rather
        than applying an override to a stale section.
        """
        generation = getattr(self, "_section_generation", 0)
        ready = (
            getattr(self, "_section_anchor_generation", -1) == generation
            and getattr(self, "_section_anchor_width", -1) == width
        )
        if not ready:
            return None

        current: str | None = None
        for anchor in getattr(self, "_section_anchors", ()):
            if anchor.row > row:
                break
            current = anchor.identity
        return current

    def queue_section_retry(self, direction: int) -> None:
        """Retain one direction while refreshed anchors await first paint."""
        self._pending_section_direction = direction

    def consume_section_retry(self) -> int | None:
        """Return and clear the retained navigation direction."""
        direction = getattr(self, "_pending_section_direction", None)
        self._pending_section_direction = None
        return direction

    @property
    def active_section_identity(self) -> str | None:
        """Semantic identity selected by the section-navigation shortcuts."""
        return getattr(self, "_active_section_identity", None)

    @property
    def section_layout_reserve(self) -> int:
        """Current non-document trailing layout extent."""
        return getattr(self, "_section_layout_reserve", 0)

    def _configure_slow_tool_render_tick(self, agent: Agent) -> None:
        if getattr(self, "_agent_hint_mode_rendered", False):
            self._cancel_slow_tool_render_tick()
            return
        if self.attempt_pinned_number is not None:
            self._cancel_slow_tool_render_tick()
            return
        if not supports_slow_tool_sources(agent) or not slow_tool_sources_have_pending(
            agent
        ):
            self._cancel_slow_tool_render_tick()
            return
        if (
            self._slow_tool_render_timer is not None
            and self._slow_tool_tick_agent is not None
            and self._slow_tool_tick_agent.identity == agent.identity
        ):
            self._slow_tool_tick_agent = agent
            return

        self._cancel_slow_tool_render_tick()
        self._slow_tool_tick_agent = agent
        try:
            self._slow_tool_render_timer = self.set_interval(
                _SLOW_TOOL_RENDER_TICK_SECONDS,
                self._on_slow_tool_render_tick,
            )
        except Exception:
            self._slow_tool_tick_agent = None

    def _cancel_slow_tool_render_tick(self) -> None:
        if self._slow_tool_render_timer is not None:
            self._slow_tool_render_timer.stop()
            self._slow_tool_render_timer = None
        self._slow_tool_tick_agent = None

    def _on_slow_tool_render_tick(self) -> None:
        if getattr(self, "_agent_hint_mode_rendered", False):
            self._cancel_slow_tool_render_tick()
            return
        agent = self._slow_tool_tick_agent
        if agent is None:
            self._cancel_slow_tool_render_tick()
            return
        if not slow_tool_sources_have_pending(agent):
            self._cancel_slow_tool_render_tick()
            return
        if self._navigation_gate_is_active():
            return
        context = getattr(self, "_agent_detail_render_context", None)
        if context is not None and not context.is_current(
            agent.identity,
            context.generation,
            context.attempt_view_mode,
            context.attempt_pinned_number,
        ):
            self._cancel_slow_tool_render_tick()
            return
        refresh = getattr(self, "refresh_slow_tool_metadata_from_cache", None)
        if callable(refresh):
            refresh(agent)

    def _navigation_gate_is_active(self) -> bool:
        try:
            app = self.app
        except Exception:
            return False
        gate = getattr(app, "_nav_gate", None)
        is_navigating = getattr(gate, "is_navigating", None)
        return bool(callable(is_navigating) and is_navigating())

    def on_unmount(self) -> None:
        self._cancel_slow_tool_render_tick()


_UNSET = object()
_EMPTY_DOCUMENT = object()


__all__ = [
    "AgentPromptPanel",
    "aggregate_meta_fields",
    "extract_meta_fields",
    "format_meta_key",
    "load_xprompts_used",
]
