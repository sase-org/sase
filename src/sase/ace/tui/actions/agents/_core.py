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
from ._tagging import AgentTaggingMixin
from ._loading import AgentLoadingMixin
from ._notifications import AgentNotificationMixin
from ._revive import AgentRevivalMixin
from ._wait_resume import AgentWaitResumeMixin
from ._workflow_hitl import AgentWorkflowHITLMixin

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldState
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
    AgentTaggingMixin,
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

    # Phase-4 group fold (see startup.py for full documentation).
    _group_fold_state: AgentGroupFoldState
    _current_group_key: tuple[str, ...] | None

    # Agent completion tracking for notifications
    _pending_attention_count: int
    _last_unread_ids: set[str]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
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

    def _main_panel_visible_order(self) -> list[int]:
        """Return global agent indices in the order rendered on the main panel.

        Mirrors :func:`AgentList.update_list`'s tree walk at fold level 3
        so j/k navigation steps through the same sequence the user sees.
        Workflow children inherit parent grouping (per ``_grouping_keys_for``)
        and so render contiguous with their parent.
        """
        from ...models.agent_groups import build_agent_tree

        main_agents = [self._agents[i] for i in self._main_panel_indices]
        tree = build_agent_tree(main_agents, group_fold_level=3)
        return [
            self._main_panel_indices[entry.agent_idx]
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    def _active_panel_visible_order(self) -> list[int]:
        """Return the active panel's visible row order as global agent indices.

        The pinned panel renders flat (no grouping tree), so its visible
        order equals ``_pinned_panel_indices``. The main panel uses the
        group-tree walk shared with j/k navigation.
        """
        if self._pinned_panel_focused == "pinned":
            return list(self._pinned_panel_indices)
        return self._main_panel_visible_order()

    def _capture_focused_visible_pos(self) -> int | None:
        """Return the visible-row position of ``current_idx`` on the active panel.

        Returns ``None`` when there is no anchor to capture — selection is
        out of range, the focused agent lives on the inactive panel, or
        the required panel-index state is unavailable. A ``None`` result
        signals callers (kill / dismiss) to fall back to the conservative
        clamp behavior in :meth:`_restore_focus_after_removal`.
        """
        agents = getattr(self, "_agents", None)
        if not agents or not (0 <= self.current_idx < len(agents)):
            return None
        main_indices = getattr(self, "_main_panel_indices", None)
        pinned_indices = getattr(self, "_pinned_panel_indices", None)
        if main_indices is None or pinned_indices is None:
            return None
        panel_focus = getattr(self, "_pinned_panel_focused", "main")
        active = pinned_indices if panel_focus == "pinned" else main_indices
        if self.current_idx not in active:
            return None
        visible = self._active_panel_visible_order()
        try:
            return visible.index(self.current_idx)
        except ValueError:
            return None

    def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
        """Re-anchor ``current_idx`` after an in-memory removal.

        ``prior_visible_pos`` is the visible-row position of the agent that
        previously held focus, captured *before* the removal via
        :meth:`_capture_focused_visible_pos`. After the removal the same
        position points at the agent visually below the killed one; if it
        is past the end of the new visible list we fall back to the last
        visible row. When the panel is empty, panel focus is shifted and
        ``current_idx`` is clamped per the existing fallback. When
        ``prior_visible_pos`` is ``None`` the visible-anchor branch is
        skipped and only the clamp + first-of-active fallback runs.
        """
        pinned_indices = getattr(self, "_pinned_panel_indices", [])
        main_indices = getattr(self, "_main_panel_indices", [])
        panel_focus = getattr(self, "_pinned_panel_focused", "main")
        if not pinned_indices and panel_focus == "pinned":
            self._pinned_panel_focused = "main"  # type: ignore[attr-defined]
            panel_focus = "main"
        elif not main_indices and pinned_indices and panel_focus == "main":
            self._pinned_panel_focused = "pinned"  # type: ignore[attr-defined]
            panel_focus = "pinned"

        if not self._agents:
            self.current_idx = 0
            return

        if self.current_idx >= len(self._agents):
            self.current_idx = len(self._agents) - 1
        if self.current_idx < 0:
            self.current_idx = 0

        if prior_visible_pos is not None:
            try:
                visible = self._active_panel_visible_order()
            except Exception:
                visible = []
            if visible:
                target = visible[min(prior_visible_pos, len(visible) - 1)]
                self.current_idx = target
                return

        if hasattr(self, "_active_panel_indices"):
            try:
                active = self._active_panel_indices()
            except AttributeError:
                active = main_indices or pinned_indices
        else:
            active = main_indices or pinned_indices
        if active and self.current_idx not in active:
            self.current_idx = active[0]

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
