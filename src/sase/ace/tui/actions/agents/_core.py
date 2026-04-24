"""Core agent display and interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._display import AgentDisplayMixin
from ._folding import AgentFoldingMixin
from ._kill_pin import AgentKillPinMixin
from ._killing import AgentKillingMixin
from ._marking import AgentMarkingMixin
from ._ordering import AgentOrderingMixin
from ._panels import AgentPanelsMixin
from ._loading import AgentLoadingMixin
from ._notifications import AgentNotificationMixin
from ._revive import AgentRevivalMixin
from ._wait_resume import AgentWaitResumeMixin
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
    AgentKillPinMixin,
    AgentMarkingMixin,
    AgentWaitResumeMixin,
    AgentPanelsMixin,
    AgentOrderingMixin,
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
    _last_unread_ids: set[str]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _kill_persistence_inflight: set[tuple[AgentType, str, str | None]]

    # Agent search/filter query
    _agent_search_query: str

    # Debounce timer for j/k navigation detail panel updates
    _detail_update_timer: Timer | None

    # Panel focus and index maps for pinned panel split
    _pinned_panel_focused: PanelFocus
    _main_panel_indices: list[int]
    _pinned_panel_indices: list[int]
    _main_panel_idx_map: dict[int, int]
    _pinned_panel_idx_map: dict[int, int]
    _non_child_main_indices: list[int]

    # Custom agent ordering
    _agent_custom_order: list[tuple[AgentType, str, str | None]]

    # --- Panel index helpers ---

    def _build_panel_indices(self) -> None:
        """Build derived panel index maps from the canonical _agents list.

        Populates _main_panel_indices (non-pinned agents) and
        _pinned_panel_indices (pinned + dismissable agents), plus
        O(1) global-to-local lookup dicts for each panel.
        """
        # Pre-pass: collect raw_suffix values of pinned parent workflows
        # so their children can be routed to the pinned panel too.
        pinned_parent_suffixes: set[str] = set()
        for agent in self._agents:
            if (
                agent.identity in self._pinned_agents
                and agent.status in DISMISSABLE_STATUSES
                and not agent.is_workflow_child
                and agent.raw_suffix
            ):
                pinned_parent_suffixes.add(agent.raw_suffix)

        main: list[int] = []
        pinned: list[int] = []
        for i, agent in enumerate(self._agents):
            if (
                agent.identity in self._pinned_agents
                and agent.status in DISMISSABLE_STATUSES
            ):
                pinned.append(i)
            elif (
                agent.is_workflow_child
                and agent.parent_timestamp
                and agent.parent_timestamp in pinned_parent_suffixes
            ):
                pinned.append(i)
            else:
                main.append(i)
        self._main_panel_indices = main
        self._pinned_panel_indices = pinned
        self._main_panel_idx_map = {g: loc for loc, g in enumerate(main)}
        self._pinned_panel_idx_map = {g: loc for loc, g in enumerate(pinned)}
        self._non_child_main_indices = [
            i for i in main if not self._agents[i].is_workflow_child
        ]

    def _global_to_local(self, global_idx: int) -> tuple[PanelFocus, int]:
        """Convert a global _agents index to (panel, local_index).

        Returns ("main", local_idx) or ("pinned", local_idx).
        Raises ValueError if global_idx is not in either panel.
        """
        local = self._main_panel_idx_map.get(global_idx)
        if local is not None:
            return ("main", local)
        local = self._pinned_panel_idx_map.get(global_idx)
        if local is not None:
            return ("pinned", local)
        raise ValueError(f"Global index {global_idx} not in any panel")

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

    def _active_panel_idx_map(self) -> dict[int, int]:
        """Get the O(1) index lookup map for the currently focused panel."""
        if self._pinned_panel_focused == "pinned":
            return self._pinned_panel_idx_map
        return self._main_panel_idx_map

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

    def _resolve_agent_cl_name(self, agent: Agent) -> str | None:
        """Resolve the effective ChangeSpec name for navigation.

        For workflow step children, looks up the parent workflow's cl_name
        (since children have step_name as cl_name, not a real ChangeSpec).
        For project agents, checks meta output variables.
        For all others, uses agent.cl_name directly.

        Returns None when the resolved name is "unknown" or empty.
        """
        # Workflow step children: resolve via parent
        if agent.parent_workflow is not None:
            cl_name = self._resolve_workflow_child_cl_name(agent)
            if not cl_name or cl_name == "unknown":
                return None
            return cl_name

        # Project agents: check meta output
        if agent.is_project_agent:
            from ._notification_actions import get_meta_changespec_name

            return get_meta_changespec_name(agent)

        # All others (including follow-up agents): use cl_name directly
        cl_name = agent.cl_name
        if not cl_name or cl_name == "unknown":
            return None
        return cl_name

    def _resolve_workflow_child_cl_name(self, agent: Agent) -> str | None:
        """Resolve cl_name for a workflow step child by finding its parent."""
        for candidate in self._agents_with_children:
            if candidate.is_workflow_child:
                continue
            if candidate.raw_suffix != agent.parent_timestamp:
                continue
            if candidate.workflow != agent.parent_workflow:
                continue
            return candidate.cl_name

        # Parent not in list — read workflow_state.json directly
        return self._read_workflow_state_cl_name(agent)

    @staticmethod
    def _read_workflow_state_cl_name(agent: Agent) -> str | None:
        """Read cl_name from workflow_state.json for a workflow child."""
        import json
        from pathlib import Path

        if not agent.parent_workflow or not agent.raw_suffix:
            return None

        project_name = Path(agent.project_file).parent.name
        base_workflow = (
            agent.parent_workflow.split("/")[-1]
            if "/" in agent.parent_workflow
            else agent.parent_workflow
        )
        state_file = Path(
            f"~/.sase/projects/{project_name}/artifacts/"
            f"workflow-{base_workflow}/{agent.raw_suffix}/workflow_state.json"
        ).expanduser()

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("context", {}).get("cl_name")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def action_jump_to_agent_changespec(self) -> None:
        """Jump to the CLs tab selecting the ChangeSpec for the current agent."""
        if self.current_tab != "agents":
            return
        agent = self._get_selected_agent()
        if agent is None:
            return

        cs_name = self._resolve_agent_cl_name(agent)
        if not cs_name:
            self.notify("No ChangeSpec for this agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ._notification_actions import navigate_to_changespec_tab

        navigate_to_changespec_tab(self, cs_name, agent.project_file)

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
