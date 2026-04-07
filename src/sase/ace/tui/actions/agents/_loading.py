"""Agent loading and filtering logic for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.fold_state import FoldStateManager

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Statuses that indicate an agent is dismissable (shows "x dismiss" in footer)
DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
    "PLAN COMMITTED",
    "PLAN DONE",
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


class AgentLoadingMixin:
    """Mixin providing agent loading and filtering methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    hide_non_run_agents: bool
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agents_last_idx: int
    _has_always_visible: bool
    _hidden_count: int

    # Fold state for workflow steps
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]

    # Agent completion tracking for notifications
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]

    # Agent search/filter query
    _agent_search_query: str

    # Panel focus and index maps for pinned panel split
    _pinned_panel_focused: Literal["main", "pinned"]
    _main_panel_indices: list[int]
    _pinned_panel_indices: list[int]

    # Pinned agents
    _pinned_agents: set[tuple[AgentType, str, str | None]]

    def _load_agents(self) -> None:
        """Load agents from all sources."""
        from ...models import load_all_agents

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
        # is in _dismissed_agents but not already found by the loader.
        # Only load the specific files we need (by raw_suffix).
        from ....dismissed_agents import load_dismissed_bundles

        loader_identities = {a.identity for a in dismissed_from_loader}
        loader_suffixes = {
            a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
        }
        needed_suffixes = dismissed_suffixes - loader_suffixes
        for bundled_agent in load_dismissed_bundles(needed_suffixes):
            if bundled_agent.identity not in loader_identities:
                dismissed_from_loader.append(bundled_agent)

        self._dismissed_agent_objects = dismissed_from_loader

        # Self-heal: remove orphaned dismissed entries that have no agent
        # object AND no bundle file on disk.  These are agents from before
        # the per-agent bundle system that can never be revived.
        from ....dismissed_agents import (
            _DISMISSED_BUNDLES_DIR,
            save_dismissed_agents,
        )

        found_suffixes = {
            a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
        }
        orphaned = set()
        for identity in self._dismissed_agents:
            _, _, raw_suffix = identity
            if raw_suffix is None or raw_suffix in found_suffixes:
                continue
            # Check if a bundle file exists for this suffix
            parent_path = _DISMISSED_BUNDLES_DIR / f"{raw_suffix}.json"
            has_bundle = (
                parent_path.exists()
                or any(_DISMISSED_BUNDLES_DIR.glob(f"{raw_suffix}__c*.json"))
                if _DISMISSED_BUNDLES_DIR.is_dir()
                else False
            )
            if not has_bundle:
                orphaned.add(identity)
        if orphaned:
            self._dismissed_agents -= orphaned
            save_dismissed_agents(self._dismissed_agents)

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

        # Auto-dismiss hidden agents that have completed successfully.
        # Failed agents are kept visible so the user can investigate.
        auto_dismissed = [
            a
            for a in all_agents
            if a.hidden and a.status in DISMISSABLE_STATUSES and a.status != "FAILED"
        ]
        for agent in auto_dismissed:
            self._persist_dismissed_agent(agent.identity)  # type: ignore[attr-defined]
        if auto_dismissed:
            auto_dismissed_ids = {a.identity for a in auto_dismissed}
            all_agents = [a for a in all_agents if a.identity not in auto_dismissed_ids]

        # Mark axe-spawned agents as hidden so the ◌ icon renders correctly
        for agent in all_agents:
            if not agent.hidden and _is_axe_spawned_agent(agent):
                agent.hidden = True

        # Categorize agents: always-visible (dismissable OR running) vs hideable
        always_visible: list[Agent] = []
        hideable: list[Agent] = []
        for a in all_agents:
            if _is_always_visible(a):
                always_visible.append(a)
            else:
                hideable.append(a)

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

        # Build panel index maps (must happen after _agents is finalized)
        self._build_panel_indices()  # type: ignore[attr-defined]

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

        # Ensure panel focus is valid after refresh
        if not self._pinned_panel_indices and self._pinned_panel_focused == "pinned":  # type: ignore[attr-defined]
            self._pinned_panel_focused = "main"  # type: ignore[attr-defined]
        elif (
            not self._main_panel_indices  # type: ignore[attr-defined]
            and self._pinned_panel_indices  # type: ignore[attr-defined]
            and self._pinned_panel_focused == "main"  # type: ignore[attr-defined]
        ):
            self._pinned_panel_focused = "pinned"  # type: ignore[attr-defined]

        # If selection target is not in focused panel, adjust
        if self._agents and new_idx not in self._active_panel_indices():  # type: ignore[attr-defined]
            active = self._active_panel_indices()  # type: ignore[attr-defined]
            if active:
                new_idx = active[0]

        # Only modify current_idx if we're on the agents tab
        # Otherwise, update the saved position for when user switches to agents tab
        if on_agents_tab:
            self.current_idx = new_idx
        else:
            self._agents_last_idx = new_idx

        # Update the running agent counts on the tab bar.
        # Exclude workflow children — they are sub-steps of a parent agent
        # and should not inflate the top-level running count.
        # All counts use the final displayed list (self._agents) rather than
        # the pre-filter always_visible/all_agents — fold-state filtering
        # removes workflow parents whose children are all hidden steps, so
        # the pre-filter lists can contain agents not shown in the UI.
        manual_running = sum(
            1
            for a in self._agents
            if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
        )
        if self._has_always_visible:
            hidden_running = sum(
                1
                for a in hideable
                if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
            )
        else:
            hidden_running = 0
        pinned_visible = sum(
            1
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES
            and not a.is_workflow_child
            and a.identity in self._pinned_agents
        )
        done_visible = sum(
            1
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES
            and not a.is_workflow_child
            and a.identity not in self._pinned_agents
        )
        from ...widgets import TabBar

        tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
        tab_bar.update_agents_count(
            manual_running,
            hidden_running,
            show_hidden=not self.hide_non_run_agents,
            done_count=done_visible,
            pinned_count=pinned_visible,
        )

        # Only refresh display if on agents tab
        if on_agents_tab:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
