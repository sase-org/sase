"""Agent prompt panel widget for the ace TUI."""

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
from ._workflow_display import WorkflowDisplayMixin

_SLOW_TOOL_RENDER_TICK_SECONDS = 5.0


class AgentPromptPanel(
    AgentDisplayMixin, AgentHintsDisplayMixin, WorkflowDisplayMixin, Static
):
    """Top panel showing agent details and the input prompt."""

    _slow_tool_render_timer: Timer | None = None
    _slow_tool_tick_agent: Agent | None = None

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


__all__ = [
    "AgentPromptPanel",
    "aggregate_meta_fields",
    "extract_meta_fields",
    "format_meta_key",
    "load_xprompts_used",
]
