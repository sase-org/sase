"""Agent loading and filtering logic for the ace TUI app."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import AgentContentSearchCache
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.fold_state import FoldStateManager

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec
from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    TabName,
    is_always_visible,
    is_axe_spawned_agent,
    load_agents_from_disk,
)

log = logging.getLogger(__name__)

# Per-process cache of artifact dirs already reconciled by the loader's
# self-healing pass.  First call inspects the dir (and may call
# ``delete_agent_artifacts``); subsequent full reloads skip it, saving the
# stat/glob syscalls when many dismissed agents accumulate.
_CLEANED_ARTIFACT_DIRS: set[str] = set()


def _compute_loader_cleanup(
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    dismissed_from_loader: list[Agent],
) -> tuple[
    set[tuple[AgentType, str, str | None]],
    set[str],
]:
    """Compute orphaned-dismissed entries and clean loader-sourced artifacts."""
    # Self-heal dismissed entries with no in-memory agent and no bundle file.
    from ....dismissed_agents import has_dismissed_bundle
    from ._killing import delete_agent_artifacts

    found_suffixes = {
        a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
    }
    orphaned: set[tuple[AgentType, str, str | None]] = set()
    for identity in dismissed_snapshot:
        _, _, raw_suffix = identity
        if raw_suffix is None or raw_suffix in found_suffixes:
            continue
        if not has_dismissed_bundle(raw_suffix):
            orphaned.add(identity)

    # Self-healing: clean stale artifacts only for loader-sourced dismissed agents.
    cleaned_dirs: set[str] = set()
    for a in dismissed_from_loader:
        if a._loaded_from_dismissed_bundle:
            continue
        artifacts_dir = a.artifacts_dir or a.get_artifacts_dir()
        if artifacts_dir is None or artifacts_dir in _CLEANED_ARTIFACT_DIRS:
            continue
        if not Path(artifacts_dir).is_dir():
            cleaned_dirs.add(artifacts_dir)
            continue
        delete_agent_artifacts(artifacts_dir)
        cleaned_dirs.add(artifacts_dir)

    return orphaned, cleaned_dirs


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

    # Per-group collapse state for the Agents-tab two-level grouping tree.
    # Always points to the active mode's slot in
    # ``_group_fold_registries`` (see startup.py).
    _group_fold_registry: AgentGroupFoldRegistry

    # Agent completion tracking for notifications
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]

    # Agent search/filter query
    _agent_search_query: str
    _agent_content_search_cache: AgentContentSearchCache

    # Loading guard
    _agents_loading: bool
    # Startup loading indicator flag: flipped to True once the first async
    # load completes; remains True forever afterward.
    _agents_first_load_done: bool
    # Last-request-wins coalescing: set when a refresh is requested while
    # another one is already running. The in-flight refresh re-schedules
    # itself once it finishes so the final UI state reflects disk state
    # after the last trigger.
    _agents_refresh_pending: bool
    _agents_refresh_scheduled: bool

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

        dismissed_snapshot = set(self._dismissed_agents)
        disk_start = time.perf_counter()
        all_agents, dismissed_from_loader = await asyncio.to_thread(
            load_agents_from_disk, dismissed_snapshot
        )
        disk_elapsed = time.perf_counter() - disk_start
        log.debug(
            "agents async load: disk=%.3fs agents=%d dismissed=%d",
            disk_elapsed,
            len(all_agents),
            len(dismissed_from_loader),
        )
        cleanup_start = time.perf_counter()
        orphaned, cleaned_dirs = await asyncio.to_thread(
            _compute_loader_cleanup, dismissed_snapshot, dismissed_from_loader
        )
        if orphaned:
            from ....dismissed_agents import save_dismissed_agents

            self._dismissed_agents -= orphaned
            save_dismissed_agents(self._dismissed_agents)
        if cleaned_dirs:
            _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        log.debug(
            "agents async load: cleanup=%.3fs orphaned=%d cleaned=%d",
            time.perf_counter() - cleanup_start,
            len(orphaned),
            len(cleaned_dirs),
        )

        # Capture current state AFTER the await — the user may have navigated
        # (j/k) or switched tabs while disk I/O was in flight.
        on_agents_tab = self.current_tab == "agents"
        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity

        apply_start = time.perf_counter()
        self._apply_loaded_agents(
            all_agents, dismissed_from_loader, on_agents_tab, selected_identity
        )
        log.debug("agents async load: apply=%.3fs", time.perf_counter() - apply_start)

    def _apply_loaded_agents(
        self,
        all_agents: list[Agent],
        dismissed_from_loader: list[Agent],
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
    ) -> None:
        """Apply loaded agent data to app state (main thread only)."""
        # Clear the startup loading indicators (spinner on list panels,
        # dim ellipsis on tab label / info panel) on the first completed
        # load. Safe to call every refresh -- flag stays True and the
        # widget setters are idempotent.
        if not self._agents_first_load_done:
            self._agents_first_load_done = True
            from ...widgets import AgentInfoPanel, AgentList

            try:
                self.query_one("#agent-list-panel", AgentList).loading = False  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                info_panel = self.query_one(  # type: ignore[attr-defined]
                    "#agent-info-panel", AgentInfoPanel
                )
                info_panel.set_loading(False)
            except Exception:
                pass
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]

        recovered_bundle_identities = {
            a.identity
            for a in dismissed_from_loader
            if a._loaded_from_dismissed_bundle
            and a.identity not in self._dismissed_agents
        }
        if recovered_bundle_identities:
            from ....dismissed_agents import save_dismissed_agents

            self._dismissed_agents.update(recovered_bundle_identities)
            save_dismissed_agents(self._dismissed_agents)

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
        # Keep sync callers (tests and explicit _load_agents paths) behavior
        # consistent: run cleanup inline only when no async refresh is in flight.
        if not self._agents_loading:
            orphaned, cleaned_dirs = _compute_loader_cleanup(
                set(self._dismissed_agents), dismissed_from_loader
            )
            if orphaned:
                from ....dismissed_agents import save_dismissed_agents

                self._dismissed_agents -= orphaned
                save_dismissed_agents(self._dismissed_agents)
            if cleaned_dirs:
                _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)

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
        """Schedule an async agent reload without blocking.

        If a refresh is already in flight, mark a pending follow-up so the
        in-flight run re-schedules itself once it finishes. This gives
        last-request-wins semantics: a stampede of refresh requests
        produces at most two full loads (the one already running plus one
        follow-up), and the final UI state reflects whatever was on disk
        after the last trigger.
        """
        if self._agents_loading:
            self._agents_refresh_pending = True
            return
        if self._agents_refresh_scheduled:
            self._agents_refresh_pending = True
            return
        self._agents_refresh_scheduled = True
        self.call_later(self._run_agents_async_refresh)  # type: ignore[attr-defined]

    async def _run_agents_async_refresh(self) -> None:
        """Run the async agent refresh with loading guard."""
        self._agents_refresh_scheduled = False
        if self._agents_loading:
            self._agents_refresh_pending = True
            return
        self._agents_loading = True
        try:
            await self._load_agents_async()
        finally:
            self._agents_loading = False
            # If a refresh was requested while we were running, schedule one
            # more pass so the UI reflects the latest on-disk state.
            if self._agents_refresh_pending:
                self._agents_refresh_pending = False
                self._schedule_agents_async_refresh()  # type: ignore[attr-defined]

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        """Lightweight agent refresh that skips disk I/O.

        Reuses the cached ``_agents_with_children`` list from the last full
        ``_load_agents()`` call and re-applies only the in-memory pipeline:
        fold filtering, ordering, search, status overrides, panel indices,
        selection restoration, tab-bar counts, and display refresh.

        ``prior_pos`` is the active panel's pre-mutation visible-row
        position of the focused agent — used to restore focus to the agent
        visually below the removed one when the previously selected
        identity is gone (kill / dismiss paths).

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
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            prior_pos=prior_pos,
        )

    def _finalize_agent_list(
        self,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        *,
        save_unfiltered: bool,
        prior_pos: int | None = None,
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
            prior_pos: Pre-mutation visible-row position of the previously
                focused agent on the active panel. Only used when the
                selected identity is gone (kill / dismiss); routes through
                :meth:`_restore_focus_after_removal` so focus lands on the
                agent visually below the removed one.
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

        # Apply agent search filter (case-insensitive substring match).
        # The haystack includes metadata fields plus each agent's cached
        # prompt/reply content — see ``AgentContentSearchCache``. Content
        # reads only happen when a query is active.
        if self._agent_search_query:
            query_lower = self._agent_search_query.lower()
            content_cache = self._agent_content_search_cache

            def _matches(agent: Agent) -> bool:
                for field in ("cl_name", "display_name", "agent_name", "status"):
                    value = getattr(agent, field, "") or ""
                    if query_lower in value.lower():
                        return True
                haystack = content_cache.get_haystack(agent)
                return bool(haystack) and query_lower in haystack

            # Collect identities of matching parents so children stay visible
            matching_parent_names: set[str] = set()
            for agent in self._agents:
                if not agent.is_workflow_child and _matches(agent):
                    matching_parent_names.add(agent.agent_name or agent.cl_name)

            self._agents = [
                a
                for a in self._agents
                if (
                    _matches(a)
                    # Or child of a matching parent (preserve hierarchy)
                    or (
                        a.is_workflow_child
                        and (a.agent_name or a.cl_name) in matching_parent_names
                    )
                )
            ]
            # Release cache entries for agents no longer in the list so
            # memory stays bounded across many refresh cycles.
            content_cache.prune(self._agents)

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

        # Calculate the new index
        # Use current_idx when on agents tab, otherwise use saved _agents_last_idx
        saved_idx = self.current_idx if on_agents_tab else self._agents_last_idx

        identity_restored = False
        if selected_identity is not None:
            # Try to restore selection by identity
            for idx, agent in enumerate(self._agents):
                if agent.identity == selected_identity:
                    saved_idx = idx
                    identity_restored = True
                    break
            # If agent not found, saved_idx remains at the original position

        # When the previously selected identity is gone (kill / dismiss),
        # re-anchor focus to the agent that now occupies the same visible
        # row the killed one had.  Only the on-agents-tab branch needs this
        # — the saved-idx branch is just a stash for tab switches.
        if (
            on_agents_tab
            and prior_pos is not None
            and selected_identity is not None
            and not identity_restored
        ):
            self.current_idx = saved_idx
            self._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]
        else:
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

        # Garbage-collect collapse entries for groups that vanished after
        # the latest fold/search/filter pipeline so a re-appearing group
        # key never inherits stale collapse state.  ``_grouping_mode`` is
        # the active L0 layout — keys for inactive modes live in their
        # own registry slot and stay untouched.
        from ...models.agent_groups import enumerate_group_keys

        grouping_mode = getattr(self, "_grouping_mode", None)
        if grouping_mode is None:
            from ...models.agent_groups import GroupingMode

            grouping_mode = GroupingMode.STANDARD
        self._group_fold_registry.clear_unknown(
            enumerate_group_keys(self._agents, mode=grouping_mode)
        )

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
        done_visible = sum(
            1
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES and not a.is_workflow_child
        )
        from ...widgets import TabBar

        try:
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
            tab_bar.update_agents_count(
                manual_running,
                hidden_running,
                show_hidden=not self.hide_non_run_agents,
                done_count=done_visible,
            )
        except Exception:
            pass

        # Only refresh display if on agents tab
        if on_agents_tab:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True,
                defer_detail=True,
            )
            # Refresh the file panel for the now-selected agent. Silently
            # skip when nothing is selected or the agent is dismissable so
            # auto-refresh doesn't spam notifications.
            selected_agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if (
                selected_agent is not None
                and selected_agent.status not in DISMISSABLE_STATUSES
            ):
                from ...widgets import AgentDetail

                try:
                    agent_detail = self.query_one(  # type: ignore[attr-defined]
                        "#agent-detail-panel", AgentDetail
                    )
                except Exception:
                    agent_detail = None
                if agent_detail is not None:
                    agent_detail.refresh_current_file(selected_agent)
