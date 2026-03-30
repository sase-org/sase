"""Core agent display and interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._display import AgentDisplayMixin
from ._folding import AgentFoldingMixin
from ._interaction import AgentInteractionMixin
from ._killing import AgentKillingMixin
from ._loading import AgentLoadingMixin
from ._notifications import AgentNotificationMixin
from ._revive import AgentRevivalMixin
from ._workflow_hitl import AgentWorkflowHITLMixin

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.fold_state import FoldStateManager

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Re-export constants for backwards compatibility (imported by other modules)
from ._display import PanelFocus
from ._loading import DISMISSABLE_STATUSES

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentsMixinCore(
    AgentFoldingMixin,
    AgentInteractionMixin,
    AgentWorkflowHITLMixin,
    AgentNotificationMixin,
    AgentKillingMixin,
    AgentRevivalMixin,
    AgentLoadingMixin,
    AgentDisplayMixin,
):
    """Core mixin providing agent loading, display, and user interaction methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    hide_non_run_agents: bool
    _countdown_remaining: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agents_last_idx: int
    _has_always_visible: bool
    _hidden_count: int

    # Fold state for workflow steps
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]

    # Agent completion tracking for notifications
    _pending_attention_count: int
    _last_unread_count: int
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]

    # Agent search/filter query
    _agent_search_query: str

    # Debounce timer for j/k navigation detail panel updates
    _detail_update_timer: Timer | None

    # Panel focus and index maps for pinned panel split
    _pinned_panel_focused: PanelFocus
    _main_panel_indices: list[int]
    _pinned_panel_indices: list[int]

    # --- Panel index helpers ---

    def _build_panel_indices(self) -> None:
        """Build derived panel index maps from the canonical _agents list.

        Populates _main_panel_indices (non-pinned agents) and
        _pinned_panel_indices (pinned + dismissable agents).
        """
        main: list[int] = []
        pinned: list[int] = []
        for i, agent in enumerate(self._agents):
            if (
                agent.identity in self._pinned_agents
                and agent.status in DISMISSABLE_STATUSES
            ):
                pinned.append(i)
            else:
                main.append(i)
        self._main_panel_indices = main
        self._pinned_panel_indices = pinned

    def _global_to_local(self, global_idx: int) -> tuple[PanelFocus, int]:
        """Convert a global _agents index to (panel, local_index).

        Returns ("main", local_idx) or ("pinned", local_idx).
        Raises ValueError if global_idx is not in either panel.
        """
        try:
            return ("main", self._main_panel_indices.index(global_idx))
        except ValueError:
            pass
        try:
            return ("pinned", self._pinned_panel_indices.index(global_idx))
        except ValueError:
            raise ValueError(f"Global index {global_idx} not in any panel") from None

    def _local_to_global(self, panel: PanelFocus, local_idx: int) -> int:
        """Convert a (panel, local_index) to a global _agents index."""
        indices = (
            self._main_panel_indices if panel == "main" else self._pinned_panel_indices
        )
        return indices[local_idx]

    def _active_panel_indices(self) -> list[int]:
        """Get the index map for the currently focused panel."""
        if self._pinned_panel_focused == "pinned":
            return self._pinned_panel_indices
        return self._main_panel_indices

    def _switch_panel_focus(self, target: PanelFocus) -> None:
        """Switch panel focus safely, selecting first item if needed."""
        if self._pinned_panel_focused == target:
            return
        self._pinned_panel_focused = target
        indices = self._active_panel_indices()
        if indices:
            self.current_idx = indices[0]

    def _get_selected_agent(self) -> Agent | None:
        """Get the currently selected agent, or None if no valid selection."""
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    # --- Actions ---

    def _toggle_hide_non_run_agents(self) -> None:
        """Toggle visibility of non-run agents and refresh the display."""
        self.hide_non_run_agents = not self.hide_non_run_agents
        self._load_agents()

    def action_jump_to_agent_changespec(self) -> None:
        """Jump to the CLs tab selecting the ChangeSpec for the current agent."""
        if self.current_tab != "agents":
            return
        agent = self._get_selected_agent()
        if agent is None:
            return

        from ._notification_actions import (
            get_meta_changespec_name,
            navigate_to_changespec_tab,
        )

        if agent.is_project_agent:
            # Project agents can still jump if they created a CL/PR
            cs_name = get_meta_changespec_name(agent)
            if cs_name:
                navigate_to_changespec_tab(self, cs_name, agent.project_file)
            return

        navigate_to_changespec_tab(self, agent.cl_name, agent.project_file)

    def _edit_agent_search_query(self) -> None:
        """Open modal to edit the agent search/filter query."""
        from ...modals import QueryEditModal

        def on_dismiss(new_query: str | None) -> None:
            if new_query is None:
                return
            self._agent_search_query = new_query
            self._load_agents()

        self.push_screen(  # type: ignore[attr-defined]
            QueryEditModal(self._agent_search_query, title="Filter Agents"),
            on_dismiss,
        )
