"""Core agent display and interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ._approve import AgentApproveMixin
from ._display import AgentDisplayMixin
from ._folding import AgentFoldingMixin
from ._grouping import AgentGroupingMixin
from ._kill_action import AgentKillMixin
from ._killing import AgentKillingMixin
from ._loading import AgentLoadingMixin
from ._marking import AgentMarkingMixin
from ._notifications import AgentNotificationMixin
from ._panels import AgentPanelsMixin
from ._revive import AgentRevivalMixin
from ._tagging import AgentTaggingMixin
from ._wait_resume import AgentWaitResumeMixin
from ._workflow_hitl import AgentWorkflowHITLMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup
    from ...models.fold_state import FoldStateManager
    from ...util.debounce import DetailPanelDebouncer

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Re-export constants for backwards compatibility (imported by other modules)
from ._loading import DISMISSABLE_STATUSES

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentsMixinCore(
    AgentApproveMixin,
    AgentFoldingMixin,
    AgentGroupingMixin,
    AgentKillMixin,
    AgentMarkingMixin,
    AgentTaggingMixin,
    AgentWaitResumeMixin,
    AgentPanelsMixin,
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

    # Group fold + tag-driven panel collection (see startup.py for full
    # documentation).
    _group_fold_registry: AgentGroupFoldRegistry
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool

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

    # Debouncer for j/k navigation detail panel updates
    _agent_detail_debouncer: DetailPanelDebouncer

    # Phase 2 j/k caches (initialized in StartupMixin._init_app_state).
    _nav_stops_cache: tuple[Any, ...] | None

    def _agents_visible_order(self) -> list[int]:
        """Return global agent indices in the order rendered on the focused panel.

        Mirrors :func:`AgentList.update_list`'s tree walk so j/k
        navigation steps through the same sequence the user sees.
        Agents inside collapsed groups are excluded — their indices
        never appear because the renderer hides them.  Only agents in
        the currently focused tag panel are returned; workflow children
        inherit parent grouping (per ``_grouping_keys_for``) and so
        render contiguous with their parent.
        """
        from ...models.agent_groups import build_agent_tree
        from ...models.agent_panels import agents_for_panel

        from ...models.agent_groups import GroupingMode

        registry = getattr(self, "_group_fold_registry", None)
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            tree = build_agent_tree(self._agents, fold_registry=registry, mode=mode)
            return [
                entry.agent_idx
                for entry in tree
                if entry.kind == "agent" and entry.agent_idx is not None
            ]
        focused_key = panel_group.focused_key
        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == focused_key]
        panel_agents = agents_for_panel(
            self._agents, focused_key, merge_tag_panels=merge_tag_panels
        )
        tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
        return [
            global_indices[entry.agent_idx]
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    def _panel_navigation_stops(
        self,
    ) -> list[tuple[str, int | tuple[str, ...]]]:
        """Return the focused panel's selectable rows in render order.

        Each entry is ``("agent", global_idx)`` for a visible agent row
        or ``("banner", group_key)`` for a collapsed banner row.  Used
        by j/k navigation to cycle through every selectable stop —
        including stepping in and out of collapsed groups.

        Memoized: under j/k autorepeat the inputs (agents list,
        focused panel, fold state, grouping mode) don't change between
        keystrokes, so the tree rebuild is amortized to one per refresh
        cycle.  Cache invalidates implicitly when any input changes
        identity / version.
        """
        from ...models.agent_groups import build_agent_tree
        from ...models.agent_panels import agents_for_panel

        from ...models.agent_groups import GroupingMode

        registry = getattr(self, "_group_fold_registry", None)
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        panel_group = getattr(self, "_panel_group", None)

        fold_version = registry.version if registry is not None else 0
        cached = getattr(self, "_nav_stops_cache", None)
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] is panel_group
            and cached[2]
            == (panel_group.focused_idx if panel_group is not None else None)
            and cached[3] == fold_version
            and cached[4] is mode
            and cached[5] == merge_tag_panels
        ):
            return cached[6]

        if panel_group is None:
            tree = build_agent_tree(self._agents, fold_registry=registry, mode=mode)
            stops: list[tuple[str, int | tuple[str, ...]]] = []
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        stops.append(("banner", entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    stops.append(("agent", entry.agent_idx))
        else:
            focused_key = panel_group.focused_key
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            global_indices = [
                i for i, k in enumerate(keys_per_agent) if k == focused_key
            ]
            panel_agents = agents_for_panel(
                self._agents, focused_key, merge_tag_panels=merge_tag_panels
            )
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            stops = []
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        stops.append(("banner", entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    stops.append(("agent", global_indices[entry.agent_idx]))

        self._nav_stops_cache = (
            self._agents,
            panel_group,
            panel_group.focused_idx if panel_group is not None else None,
            fold_version,
            mode,
            merge_tag_panels,
            stops,
        )
        return stops

    def _capture_focused_visible_pos(self) -> int | None:
        """Return the rendered selectable-row position of the current focus.

        The Agents tab can focus either an agent row (``current_idx``)
        or a collapsed group banner (``_current_group_key``). Capture the
        position in ``_panel_navigation_stops()`` so removals restore to
        the next surviving selectable row in the same order j/k uses.
        Returns ``None`` when the current focus is no longer rendered.
        """
        agents = getattr(self, "_agents", None)
        if not agents:
            return None

        try:
            stops = self._panel_navigation_stops()
        except Exception:
            stops = []

        current_group_key = getattr(self, "_current_group_key", None)
        if current_group_key is not None:
            for pos, (kind, payload) in enumerate(stops):
                if kind == "banner" and payload == current_group_key:
                    return pos

        if 0 <= self.current_idx < len(agents):
            for pos, (kind, payload) in enumerate(stops):
                if kind == "agent" and payload == self.current_idx:
                    return pos
        return None

    def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
        """Re-anchor focus after an in-memory removal.

        ``prior_visible_pos`` is the pre-removal position in
        ``_panel_navigation_stops()``. After removal, the same position
        points at the row visually below the removed one, clamped to the
        last surviving stop. Agent stops clear banner focus and update
        ``current_idx``; banner stops preserve banner focus and keep
        ``current_idx`` clamped to a valid backing index.
        """
        if not self._agents:
            self.current_idx = 0
            self._current_group_key = None
            return

        if self.current_idx >= len(self._agents):
            self.current_idx = len(self._agents) - 1
        if self.current_idx < 0:
            self.current_idx = 0

        try:
            stops = self._panel_navigation_stops()
        except Exception:
            stops = []

        if prior_visible_pos is not None and stops:
            kind, payload = stops[min(prior_visible_pos, len(stops) - 1)]
            if kind == "banner":
                assert isinstance(payload, tuple)
                self._current_group_key = payload
            else:
                assert isinstance(payload, int)
                self._current_group_key = None
                self.current_idx = payload
            return

        if self._current_group_key is not None and not any(
            kind == "banner" and payload == self._current_group_key
            for kind, payload in stops
        ):
            self._current_group_key = None

    def _get_selected_agent(self) -> Agent | None:
        """Get the currently selected agent, or None if no valid selection."""
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _agents_in_focused_panel(self) -> list[Agent]:
        """Return the agents in the currently focused tag panel.

        Falls back to the full agent list when ``_panel_group`` has not
        been built yet (early lifecycle window before the first refresh).
        """
        from ...models.agent_panels import agents_for_panel

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return list(self._agents)
        return agents_for_panel(
            self._agents,
            panel_group.focused_key,
            merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
        )

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
        from ....agent_query import parse_agent_query
        from ...modals import QueryEditModal

        def on_dismiss(new_query: str | None) -> None:
            if new_query is None:
                return
            self._agent_search_query = new_query
            self._load_agents()

        def _validator(value: str) -> None:
            if value:
                parse_agent_query(value)

        hint = (
            "status:foo  cl:bar  project:baz  age>2h  attention:true  "
            "AND/OR/NOT  (?: help)"
        )
        initial_error = getattr(self, "_agent_query_parse_error", None)
        self.push_screen(  # type: ignore[attr-defined]
            QueryEditModal(
                self._agent_search_query,
                title="Filter Agents",
                hint=hint,
                validator=_validator,
                initial_error=initial_error,
            ),
            on_dismiss,
        )
