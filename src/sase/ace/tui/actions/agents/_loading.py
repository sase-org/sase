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
from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    TabName,
    apply_custom_order,
    is_always_visible,
    is_axe_spawned_agent,
    load_agents_from_disk,
)


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
    _hideable_agents: list[Agent]

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

    # Loading guard
    _agents_loading: bool

    # Panel focus and index maps for pinned panel split
    _pinned_panel_focused: Literal["main", "pinned"]
    _main_panel_indices: list[int]
    _pinned_panel_indices: list[int]

    # Pinned agents
    _pinned_agents: set[tuple[AgentType, str, str | None]]

    # Custom agent ordering
    _agent_custom_order: list[tuple[AgentType, str, str | None]]

    def _load_agents(self) -> None:
        """Load agents from all sources."""
        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity

        dismissed_snapshot = set(self._dismissed_agents)
        all_agents, dismissed_from_loader = load_agents_from_disk(dismissed_snapshot)
        self._apply_loaded_agents(
            all_agents, dismissed_from_loader, on_agents_tab, selected_identity
        )

    async def _load_agents_async(self) -> None:
        """Load agents with disk IO in a background thread."""
        import asyncio

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity

        dismissed_snapshot = set(self._dismissed_agents)
        all_agents, dismissed_from_loader = await asyncio.to_thread(
            load_agents_from_disk, dismissed_snapshot
        )
        self._apply_loaded_agents(
            all_agents, dismissed_from_loader, on_agents_tab, selected_identity
        )

    def _apply_loaded_agents(
        self,
        all_agents: list[Agent],
        dismissed_from_loader: list[Agent],
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
    ) -> None:
        """Apply loaded agent data to app state (main thread only)."""
        # Build dismissed indices for filtering
        dismissed_suffixes: set[str] = {
            raw_suffix
            for _, _, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }
        dismissed_cl_suffixes: set[tuple[str, str]] = {
            (cl_name, raw_suffix)
            for _, cl_name, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }

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

        loader_identities = {a.identity for a in dismissed_from_loader}
        loader_suffixes = {
            a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
        }
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

        # Mark axe-spawned agents as hidden so the icon renders correctly
        for agent in all_agents:
            if not agent.hidden and is_axe_spawned_agent(agent):
                agent.hidden = True

        # Categorize agents: always-visible (dismissable OR running) vs hideable
        always_visible: list[Agent] = []
        hideable: list[Agent] = []
        for a in all_agents:
            if is_always_visible(a):
                always_visible.append(a)
            else:
                hideable.append(a)

        self._has_always_visible = len(always_visible) > 0
        self._hidden_count = 0
        self._hideable_agents = hideable

        # Filter if we have always-visible agents and hiding is enabled
        if self._has_always_visible and self.hide_non_run_agents and hideable:
            self._agents = always_visible
            self._hidden_count = len(hideable)
        else:
            self._agents = all_agents

        self._finalize_agent_list(
            on_agents_tab, selected_identity, save_unfiltered=True
        )

    def _schedule_agents_async_refresh(self) -> None:
        """Schedule an async agent reload without blocking."""
        if self._agents_loading:
            return
        self.call_later(self._run_agents_async_refresh)  # type: ignore[attr-defined]

    async def _run_agents_async_refresh(self) -> None:
        """Run the async agent refresh with loading guard."""
        if self._agents_loading:
            return
        self._agents_loading = True
        try:
            await self._load_agents_async()
        finally:
            self._agents_loading = False

    def _refilter_agents(self) -> None:
        """Lightweight agent refresh that skips disk I/O.

        Reuses the cached ``_agents_with_children`` list from the last full
        ``_load_agents()`` call and re-applies only the in-memory pipeline:
        fold filtering, ordering, search, status overrides, panel indices,
        selection restoration, tab-bar counts, and display refresh.

        Falls back to ``_load_agents()`` if no full load has run yet.
        """
        # Guard: first load hasn't happened yet
        if not self._agents_with_children:
            self._load_agents()
            return

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity

        # Start from the cached unfiltered list (already has dismiss/hide applied)
        self._agents = list(self._agents_with_children)

        self._finalize_agent_list(
            on_agents_tab, selected_identity, save_unfiltered=False
        )

    def _finalize_agent_list(
        self,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        *,
        save_unfiltered: bool,
    ) -> None:
        """Shared post-processing pipeline for agent list finalization.

        Applies fold filtering, custom ordering, search filter, status
        overrides, panel indices, selection restoration, tab-bar counts,
        and display refresh.

        Args:
            on_agents_tab: Whether the agents tab is currently active.
            selected_identity: Identity of the previously selected agent.
            save_unfiltered: If True, save ``_agents_with_children`` before
                fold filtering (used by full load, not refilter).
        """
        # Apply fold-state filtering for workflow children
        from ...models import filter_agents_by_fold_state

        if save_unfiltered:
            # Save unfiltered list (with children) for bundle/dismiss operations
            # that need to find child steps even when fold state is COLLAPSED.
            self._agents_with_children = list(self._agents)
        self._agents, self._fold_counts = filter_agents_by_fold_state(
            self._agents, self._fold_manager
        )

        # Apply custom ordering (user-defined via J/K move)
        if self._agent_custom_order:
            self._agents = apply_custom_order(self._agents, self._agent_custom_order)

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
                # -- clear any override
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
        # Exclude workflow children -- they are sub-steps of a parent agent
        # and should not inflate the top-level running count.
        # All counts use the final displayed list (self._agents) rather than
        # the pre-filter always_visible/all_agents -- fold-state filtering
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
                for a in self._hideable_agents
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
