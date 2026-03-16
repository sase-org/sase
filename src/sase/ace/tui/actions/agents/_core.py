"""Core agent display and interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._folding import AgentFoldingMixin
from ._interaction import AgentInteractionMixin
from ._interrupt import AgentInterruptMixin
from ._killing import AgentKillingMixin
from ._notifications import AgentNotificationMixin
from ._revive import AgentRevivalMixin
from ._workflow_hitl import AgentWorkflowHITLMixin

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.fold_state import FoldStateManager
    from ...widgets import AgentDetail, KeybindingFooter

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Statuses that indicate an agent is dismissable (shows "x dismiss" in footer)
DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
}


def _is_always_visible(agent: Agent) -> bool:
    """Check if agent should always be visible (dismissable or running).

    Args:
        agent: The agent to check.

    Returns:
        True if agent should always be visible, False if it's hideable.
    """
    # Workflow children: visibility managed by fold state, not hide toggle
    if agent.is_workflow_child:
        return True

    # Agents marked hidden (via %hide directive, axe-spawned detection, etc.)
    # are hideable (hidden by default, shown with '.' toggle)
    if agent.hidden:
        return False

    return True


def _is_axe_spawned_agent(agent: Agent) -> bool:
    """Check if agent was spawned by sase axe (not user-initiated).

    Agents spawned by axe should not trigger notifications since they're
    automated background tasks.

    Args:
        agent: The agent to check.

    Returns:
        True if agent was spawned by axe, False if user-initiated.
    """
    if agent.workflow:
        # Normalize hyphens to underscores (canonical form uses underscores,
        # e.g. xprompt workflow_label "fix_hook")
        workflow = agent.workflow.replace("-", "_")
        # axe-spawned workflows start with axe(...)
        if workflow.startswith(("axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor(")):
            return True
        # Plain workflow names for axe-spawned types (from workflow_state.json or ChangeSpec)
        if workflow in ("fix_hook", "crs", "mentor", "summarize_hook"):
            return True

    return False


class AgentsMixinCore(
    AgentFoldingMixin,
    AgentInteractionMixin,
    AgentInterruptMixin,
    AgentWorkflowHITLMixin,
    AgentNotificationMixin,
    AgentKillingMixin,
    AgentRevivalMixin,
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

    def _load_agents(self) -> None:
        """Load agents from all sources."""
        from ...models import load_all_agents
        from ...models.agent import AgentType

        # Only capture selection identity if we're on the agents tab
        # (current_idx refers to changespecs when on changespecs tab)
        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity

        # Load fresh agent list
        all_agents = load_all_agents()

        # Populate retry fields from retry_state.json for running agents
        from sase.llm_provider.retry_config import RetryState

        for agent in all_agents:
            if agent.status != "RUNNING":
                continue
            artifacts_dir = agent.get_artifacts_dir()
            if not artifacts_dir:
                continue
            retry_state = RetryState.read_from(artifacts_dir)
            if retry_state is None:
                continue
            agent.retry_count = retry_state.retry_count
            agent.max_retries = retry_state.max_retries
            agent.retry_next_at_epoch = retry_state.next_retry_at_epoch
            agent.retry_wait_seconds = retry_state.wait_seconds
            agent.using_fallback = retry_state.using_fallback
            agent.fallback_model = retry_state.fallback_model
            agent.retry_status = retry_state.status
            # Override display status for "retrying" state
            if retry_state.status == "retrying":
                agent.status = "RETRYING"

        # Build secondary index for robust dismissed matching
        # (agent cl_name or type may change between loads due to dedup merging)
        dismissed_suffixes: set[str] = {
            raw_suffix
            for _, _, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }

        # Build (cl_name, raw_suffix) pairs for cross-type matching of
        # RUNNING agents.  When a WORKFLOW agent is killed and its artifacts
        # are deleted, the RUNNING field entry may persist and produce an
        # agent with AgentType.RUNNING — a direct identity mismatch that
        # the primary identity check misses.
        dismissed_cl_suffixes: set[tuple[str, str]] = {
            (cl_name, raw_suffix)
            for _, cl_name, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }

        # Capture dismissed agents found by the loader (for revive + self-healing).
        # Exclude RUNNING agents: a done.json auto-dismiss can share the same
        # identity/raw_suffix as a still-active RUNNING field agent; treating the
        # running agent as dismissed would delete its artifacts and hide it.
        dismissed_from_loader = [
            a
            for a in all_agents
            if a.status != "RUNNING"
            and (
                a.identity in self._dismissed_agents
                or (a.raw_suffix is not None and a.raw_suffix in dismissed_suffixes)
            )
        ]

        # Supplement with bundles: load saved bundles for agents whose identity
        # is in _dismissed_agents but not already found by the loader
        from ....dismissed_agents import load_dismissed_bundles

        loader_identities = {a.identity for a in dismissed_from_loader}
        loader_suffixes = {
            a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
        }
        for bundled_agent in load_dismissed_bundles():
            if bundled_agent.identity in loader_identities:
                continue
            if (
                bundled_agent.raw_suffix is not None
                and bundled_agent.raw_suffix in loader_suffixes
            ):
                continue
            # Only include if this agent is actually in the dismissed set
            if bundled_agent.identity in self._dismissed_agents or (
                bundled_agent.raw_suffix is not None
                and bundled_agent.raw_suffix in dismissed_suffixes
            ):
                dismissed_from_loader.append(bundled_agent)

        self._dismissed_agent_objects = dismissed_from_loader

        # Filter out dismissed agents.  Non-RUNNING agents use the broad
        # dismissed_suffixes index (suffix-only).  RUNNING agents use the
        # narrower dismissed_cl_suffixes index (cl_name, raw_suffix) to
        # avoid cross-CL contamination while still catching agents that
        # reappear with a different AgentType after dedup (e.g. a killed
        # WORKFLOW agent whose artifacts are deleted but whose RUNNING
        # field entry persists, producing an AgentType.RUNNING agent).
        # RUNNING agents with cl_name="unknown" fall back to suffix-only
        # matching since "unknown" is a transient placeholder from the
        # RUNNING field that gets resolved during dedup.
        all_agents = [
            a
            for a in all_agents
            if a.identity not in self._dismissed_agents
            and (
                a.status == "RUNNING"
                or (a.raw_suffix is None or a.raw_suffix not in dismissed_suffixes)
            )
            and not (
                a.status == "RUNNING"
                and a.raw_suffix is not None
                and (
                    (a.cl_name, a.raw_suffix) in dismissed_cl_suffixes
                    or (a.cl_name == "unknown" and a.raw_suffix in dismissed_suffixes)
                )
            )
        ]

        # Self-healing: clean up stale artifacts only for loader-sourced
        # dismissed agents (bundle-sourced agents have no artifacts to clean)
        from ._killing import delete_agent_artifacts

        for a in self._dismissed_agent_objects:
            if a.identity in loader_identities or (
                a.raw_suffix is not None and a.raw_suffix in loader_suffixes
            ):
                delete_agent_artifacts(a.artifacts_dir or a.get_artifacts_dir())

        # Auto-dismiss hidden agents that have reached DONE or FAILED status.
        # This ensures hidden agents disappear automatically when complete
        # rather than sitting in a dismissable state behind the '.' toggle.
        auto_dismissed = [
            a for a in all_agents if a.hidden and a.status in DISMISSABLE_STATUSES
        ]
        for agent in auto_dismissed:
            self._persist_dismissed_agent(agent.identity)
        if auto_dismissed:
            auto_dismissed_ids = {a.identity for a in auto_dismissed}
            all_agents = [a for a in all_agents if a.identity not in auto_dismissed_ids]

        # Mark axe-spawned agents as hidden so the ◌ icon renders correctly
        for agent in all_agents:
            if not agent.hidden and _is_axe_spawned_agent(agent):
                agent.hidden = True

        # Categorize agents: always-visible (dismissable OR running) vs hideable
        always_visible = [a for a in all_agents if _is_always_visible(a)]
        hideable = [a for a in all_agents if not _is_always_visible(a)]

        self._has_always_visible = len(always_visible) > 0
        self._hidden_count = 0

        # Filter if we have always-visible agents and hiding is enabled
        if self._has_always_visible and self.hide_non_run_agents and hideable:
            self._agents = always_visible
            self._hidden_count = len(hideable)
        else:
            self._agents = all_agents

        # Apply fold-state filtering for workflow children
        from ...models import filter_agents_by_fold_state

        # Save unfiltered list (with children) for bundle/dismiss operations
        # that need to find child steps even when fold state is COLLAPSED.
        self._agents_with_children = list(self._agents)
        self._agents, self._fold_counts = filter_agents_by_fold_state(
            self._agents, self._fold_manager
        )

        # Apply agent search filter (case-insensitive substring match)
        if self._agent_search_query:
            query_lower = self._agent_search_query.lower()
            # Collect identities of matching parents so children stay visible
            matching_parent_names: set[str] = set()
            for agent in self._agents:
                if not agent.is_workflow_child and any(
                    query_lower in (getattr(agent, field, "") or "").lower()
                    for field in ("cl_name", "display_name", "agent_name", "status")
                ):
                    matching_parent_names.add(agent.agent_name or agent.cl_name)

            self._agents = [
                a
                for a in self._agents
                if (
                    # Direct match
                    any(
                        query_lower in (getattr(a, field, "") or "").lower()
                        for field in ("cl_name", "display_name", "agent_name", "status")
                    )
                    # Or child of a matching parent (preserve hierarchy)
                    or (
                        a.is_workflow_child
                        and (a.agent_name or a.cl_name) in matching_parent_names
                    )
                )
            ]

        # Apply status overrides (PLANNING/PLAN APPROVED/QUESTION)
        loaded_identities = {a.identity for a in self._agents}
        for agent in self._agents:
            if agent.status in DISMISSABLE_STATUSES:
                # Agent finished (DONE/FAILED, including dead-PID detection)
                # — clear any override
                self._agent_status_overrides.pop(agent.identity, None)
                self._agent_pre_question_status.pop(agent.identity, None)
            elif agent.identity in self._agent_status_overrides:
                agent.status = self._agent_status_overrides[agent.identity]

        # Clean overrides for agents that no longer exist in the loaded list
        for identity in list(self._agent_status_overrides):
            if identity not in loaded_identities:
                self._agent_status_overrides.pop(identity, None)
                self._agent_pre_question_status.pop(identity, None)

        # Calculate the new index
        # Use current_idx when on agents tab, otherwise use saved _agents_last_idx
        saved_idx = self.current_idx if on_agents_tab else self._agents_last_idx

        if selected_identity is not None:
            # Try to restore selection by identity
            for idx, agent in enumerate(self._agents):
                if agent.identity == selected_identity:
                    saved_idx = idx
                    break
            # If agent not found, saved_idx remains at the original position

        # Clamp to valid bounds
        if self._agents:
            new_idx = min(saved_idx, len(self._agents) - 1)
        else:
            new_idx = 0

        # Only modify current_idx if we're on the agents tab
        # Otherwise, update the saved position for when user switches to agents tab
        if on_agents_tab:
            self.current_idx = new_idx
        else:
            self._agents_last_idx = new_idx

        # Update the running agent counts on the tab bar.
        # Exclude workflow children — they are sub-steps of a parent agent
        # and should not inflate the top-level running count.
        if self._has_always_visible:
            manual_running = sum(
                1
                for a in always_visible
                if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
            )
            hidden_running = sum(
                1
                for a in hideable
                if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
            )
        else:
            manual_running = sum(
                1
                for a in all_agents
                if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
            )
            hidden_running = 0
        # Count done agents from the final displayed list (self._agents),
        # not the pre-filter always_visible/all_agents — fold-state filtering
        # removes workflow parents whose children are all hidden steps, so
        # the pre-filter lists can contain many more done agents than shown.
        done_visible = sum(
            1
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES and not a.is_workflow_child
        )
        from ...widgets import TabBar

        tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
        tab_bar.update_agents_count(
            manual_running,
            hidden_running,
            show_hidden=not self.hide_non_run_agents,
            done_count=done_visible,
        )

        # Only refresh display if on agents tab
        if on_agents_tab:
            self._refresh_agents_display(list_changed=True)

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        """Refresh the agents tab display.

        Args:
            list_changed: If True, the agent list has changed and needs a full
                rebuild (called from _load_agents). If False, only the selection
                index moved (j/k navigation) — skip the expensive OptionList
                clear-and-rebuild.
        """
        # Cancel any pending debounce timer — full refresh supersedes
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()
            self._detail_update_timer = None

        from ...widgets import AgentDetail, AgentList, KeybindingFooter

        agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]

        if list_changed:
            agent_list.update_list(
                self._agents, self.current_idx, fold_counts=self._fold_counts
            )
        else:
            agent_list.update_highlight(self.current_idx)

        self._apply_agent_detail_update(agent_detail, footer_widget)

        self._update_agents_info_panel()

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Updates the list highlight and position counter immediately, but
        debounces the expensive detail panel and footer updates (disk I/O,
        Rich Syntax highlighting, background workers).
        """
        from ...widgets import AgentList

        agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
        agent_list.update_highlight(self.current_idx)
        self._update_agents_info_panel()

        # Cancel any pending debounce timer before scheduling a new one
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()

        self._detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
            0.15, self._fire_debounced_detail_update
        )

    def _fire_debounced_detail_update(self) -> None:
        """Timer callback that applies the debounced detail update."""
        from ...widgets import AgentDetail, KeybindingFooter

        self._detail_update_timer = None

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        self._apply_agent_detail_update(agent_detail, footer_widget)

    def _apply_agent_detail_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
    ) -> None:
        """Apply the expensive agent detail panel and footer updates.

        Args:
            agent_detail: The agent detail panel widget.
            footer_widget: The keybinding footer widget.
        """
        current_agent = None
        if self._agents and 0 <= self.current_idx < len(self._agents):
            current_agent = self._agents[self.current_idx]
            agent_detail.update_display(
                current_agent, stale_threshold_seconds=self.refresh_interval
            )
        else:
            agent_detail.show_empty()

        if getattr(self, "_bang_mode_active", False):
            footer_widget.update_bang_bindings()
        elif getattr(self, "_copy_mode_active", False):
            file_visible = agent_detail.is_file_visible()
            footer_widget.update_copy_bindings(
                self.current_tab, file_visible=file_visible
            )
        else:
            completed_count = sum(
                1 for a in self._agents if a.status in DISMISSABLE_STATUSES
            )
            footer_widget.update_agent_bindings(
                current_agent, completed_count=completed_count
            )

    def _toggle_hide_non_run_agents(self) -> None:
        """Toggle visibility of non-run agents and refresh the display."""
        self.hide_non_run_agents = not self.hide_non_run_agents
        self._load_agents()

    def action_jump_to_agent_changespec(self) -> None:
        """Jump to the CLs tab selecting the ChangeSpec for the current agent."""
        if self.current_tab != "agents" or not self._agents:
            return
        agent = self._agents[self.current_idx]

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

    def _update_agents_info_panel(self) -> None:
        """Update the agents info panel with current position and countdown."""
        from ...widgets import AgentDetail, AgentInfoPanel

        agent_info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
        # Position is 1-based for display (current_idx is 0-based)
        position = self.current_idx + 1 if self._agents else 0
        agent_info_panel.update_position(position, len(self._agents))
        agent_info_panel.update_countdown(
            self._countdown_remaining, self.refresh_interval
        )
        agent_info_panel.update_search_query(self._agent_search_query)
        # Show current panel view mode when an agent is selected
        if self._agents and 0 <= self.current_idx < len(self._agents):
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_info_panel.update_view_mode(agent_detail.panel_mode_label)
        else:
            agent_info_panel.update_view_mode("")
