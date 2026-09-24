"""Display updates for AgentDetail (full, immediate, and hint renders)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models.agent import AgentType
from ..util.trace import tui_trace
from ._agent_detail_helpers import agent_prompt_panel_type

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_tribe_summary import TribePanelIdentity
    from .prompt_panel._agent_display_state import AgentHintRender


class AgentDetailDisplayMixin:
    """Mixin providing AgentDetail display-update entry points.

    ``metadata_identity`` and the header-sync helpers below are provided by
    ``AgentDetail`` itself.
    """

    # ------------------------------------------------------------------
    # Attribute / method declarations for type-checking. Actual values
    # are set in AgentDetail.__init__() and AgentDetail itself.
    # ------------------------------------------------------------------
    _current_agent: Agent | None
    _current_tribe_identity: TribePanelIdentity | None
    _current_attempt_number: int | None
    _attempt_view_mode: str
    _agent_detail_generation: int

    @property
    def metadata_identity(self) -> object | None:
        raise NotImplementedError

    def _publish_metadata_identity_change(self, previous: object | None) -> None:
        raise NotImplementedError

    def update_display(
        self,
        agent: Agent,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        """Update panels with agent information.

        For NO CHANGES agents, shows only prompt panel (with reply embedded).
        For NEW PR and NEW PROPOSAL agents, shows prompt and static file panels.
        For running agents, shows prompt and auto-refreshing file panels.

        Args:
            agent: The Agent to display.
            stale_threshold_seconds: Diffs older than this are refetched.
            attempt_number: When non-None, pin the detail view to the matching
                prior-attempt record (shows full error + that attempt's reply).
        """
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_tribe_identity = None
        with tui_trace("widget.agent_detail.update_display", status=agent.status):
            self._update_display_impl(
                agent,
                stale_threshold_seconds=stale_threshold_seconds,
                attempt_number=attempt_number,
            )
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()

    def update_display_immediate(
        self,
        agent: Agent,
        attempt_number: int | None = None,
    ) -> None:
        """Phase-5 immediate path: refresh prompt header without spawning workers.

        Called synchronously from the j/k debounced refresh so the user sees
        the new agent's title/status and any cached prompt content with no
        latency, while the file/LLM Calls/diff workers wait for the detail
        debouncer to settle on a final selection.
        """
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_tribe_identity = None
        with tui_trace(
            "widget.agent_detail.update_display_immediate", status=agent.status
        ):
            self._current_agent = agent
            self._current_attempt_number = attempt_number
            prompt_panel = self.query_one(
                "#agent-prompt-panel", agent_prompt_panel_type()
            )
            prompt_panel.attempt_view_mode = self._attempt_view_mode
            prompt_panel.attempt_pinned_number = attempt_number
            prompt_panel.update_header_only(agent)
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()

    def _update_display_impl(
        self,
        agent: Agent,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        self._deck_update_display_impl(  # type: ignore[attr-defined]
            agent,
            stale_threshold_seconds=stale_threshold_seconds,
            attempt_number=attempt_number,
        )

    def _should_render_workflow_detail_async(
        self, agent: Agent, attempt_number: int | None
    ) -> bool:
        return (
            attempt_number is None
            and agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        )

    def _is_agent_detail_render_current(
        self,
        agent_identity: tuple[Any, ...],
        worker_generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        """Return whether an async prompt result still matches the detail view."""
        return (
            self._agent_detail_generation == worker_generation
            and self._current_agent is not None
            and self._current_agent.identity == agent_identity
            and self._attempt_view_mode == attempt_view_mode
            and self._current_attempt_number == attempt_pinned_number
        )

    def update_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Re-render the prompt panel with file path hints.

        Scans xprompt, prompt, and chat sections for file paths and
        inserts numbered ``[N]`` markers.  Returns the hint mappings so
        the caller can process user selections.  Advancing the detail
        generation first prevents deferred work from the preceding plain
        render from replacing the annotated prompt.

        Args:
            agent: The Agent to display with hints.

        Returns:
            File hint mappings and deferred tool-call report specs.
        """
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_tribe_identity = None
        prompt_panel = self.query_one("#agent-prompt-panel", agent_prompt_panel_type())
        cancel_slow_tick = getattr(prompt_panel, "_cancel_slow_tool_render_tick", None)
        if callable(cancel_slow_tick):
            cancel_slow_tick()
        prompt_panel.attempt_view_mode = self._attempt_view_mode
        prompt_panel.attempt_pinned_number = self._current_attempt_number
        generation = self._agent_detail_generation

        set_render_context = getattr(
            prompt_panel, "set_agent_detail_render_context", None
        )
        if callable(set_render_context):
            set_render_context(
                generation=generation,
                attempt_view_mode=self._attempt_view_mode,
                attempt_pinned_number=self._current_attempt_number,
                is_current=self._is_agent_detail_render_current,
            )
        result = prompt_panel.update_display_with_hints(agent)
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()
        return result

    def hint_document_is_current(self, agent: Agent) -> bool:
        """Return whether the visible hint document already matches ``agent``."""
        prompt_panel = self.query_one("#agent-prompt-panel", agent_prompt_panel_type())
        prompt_panel.attempt_view_mode = self._attempt_view_mode
        prompt_panel.attempt_pinned_number = self._current_attempt_number
        return prompt_panel.hint_document_is_current(agent)

    def detail_header_summary_complete(self, agent: Agent) -> bool:
        """Return whether every SASE CONTEXT lane has resolved for ``agent``.

        Lets a hint-mode repaint override the "hint input has a value"
        suppression once streaming (bead sase-l6.4) finishes the last lane,
        instead of leaving the document stuck on a partial render for the
        rest of the hint session.
        """
        from .prompt_panel._agent_display_header_summary import (
            detail_header_summary_is_complete,
            get_cached_detail_header_summary,
        )

        prompt_panel = self.query_one("#agent-prompt-panel", agent_prompt_panel_type())
        summary = get_cached_detail_header_summary(prompt_panel, agent)
        return detail_header_summary_is_complete(summary)
