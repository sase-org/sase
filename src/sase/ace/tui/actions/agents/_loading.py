"""Agent loading and filtering logic for the ace TUI app.

The pure-data compute helpers (``_compute_loader_cleanup``,
``_compute_apply_loaded_agents``) live in :mod:`._loading_compute` so
they can run on a worker thread. The post-load finalize pipeline
(``finalize_agent_list``) lives in :mod:`._loading_finalize`. This
module owns the :class:`AgentLoadingMixin` class that ties them
together with the UI-thread state on ``self``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import AgentContentSearchCache
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.fold_state import FoldStateManager
    from ...util.nav_gate import NavigationGate

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec
from ._loading_compute import (
    _CLEANED_ARTIFACT_DIRS,
    PreparedApplyData,
    compute_apply_loaded_agents,
    compute_loader_cleanup,
)
from ._loading_finalize import finalize_agent_list, get_or_parse_agent_query
from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    TabName,
    load_agents_from_disk,
)

# Aliases preserved so `_loading._compute_loader_cleanup` and
# `_loading._PreparedApplyData` keep working for the test suite that
# already pokes at these names via attribute access.
_compute_loader_cleanup = compute_loader_cleanup
_compute_apply_loaded_agents = compute_apply_loaded_agents
_PreparedApplyData = PreparedApplyData

__all__ = [
    "AgentLoadingMixin",
    "DISMISSABLE_STATUSES",
    "_CLEANED_ARTIFACT_DIRS",
    "_compute_apply_loaded_agents",
    "_compute_loader_cleanup",
    "_PreparedApplyData",
]

log = logging.getLogger(__name__)


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
    # Cached (raw_query, parsed_ast) so re-renders re-use the parse. ``None``
    # AST means an empty query (no filter). The cache is invalidated whenever
    # the raw query string changes.
    _agent_query_cache: tuple[str, QueryExpr | None] | None
    # Last parse error message (for the modal to surface). ``None`` means the
    # current query parsed cleanly or is empty.
    _agent_query_parse_error: str | None

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

    # Navigation gate (set up in startup.py). Used to defer the post-await
    # apply/render leg of `_run_agents_async_refresh` while the user is
    # mid j/k burst — the same protection `_on_artifact_change` and
    # `_on_auto_refresh` already apply to their refresh triggers.
    _nav_gate: NavigationGate

    def _load_agents(self) -> None:
        """Load agents from all sources."""
        from ....changespec import find_all_changespecs_cached

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity

        dismissed_snapshot = set(self._dismissed_agents)
        changespec_snapshot = find_all_changespecs_cached()
        all_agents, dismissed_from_loader = load_agents_from_disk(
            dismissed_snapshot, changespec_snapshot=changespec_snapshot
        )
        self._apply_loaded_agents(
            all_agents, dismissed_from_loader, on_agents_tab, selected_identity
        )

    async def _load_agents_async(self) -> None:
        """Load agents with disk IO and pure-data filtering off the UI thread.

        Phase 2 of the post-launch j/k lag fix: the dismissed-set filter,
        auto-dismiss detection, axe-spawned marking, and always-visible/
        hideable categorization are computed in a worker thread via
        :func:`_compute_apply_loaded_agents`, leaving the UI thread to
        merge the prepared snapshot back into ``self`` and refresh widgets.
        Per-auto-dismiss disk writes (one ``save_dismissed_agents`` call per
        identity in the legacy path) collapse to a single batched flush.
        """
        import asyncio

        from ....changespec import find_all_changespecs_cached

        dismissed_snapshot = set(self._dismissed_agents)
        changespec_snapshot = await asyncio.to_thread(find_all_changespecs_cached)
        disk_start = time.perf_counter()
        all_agents, dismissed_from_loader = await asyncio.to_thread(
            load_agents_from_disk,
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
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
            self._dismissed_agents -= orphaned
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

        prep_start = time.perf_counter()
        # Bind the worker function to a local so ``to_thread`` doesn't see
        # the bare module-level reference on its own line — pyvision's
        # multi-line-import heuristic flags ``<name>,`` as an import
        # continuation, which would force this private helper public for
        # no semantic reason.
        prep_worker = _compute_apply_loaded_agents
        prep = await asyncio.to_thread(
            prep_worker,
            all_agents,
            dismissed_from_loader,
            set(self._dismissed_agents),
            bool(self.hide_non_run_agents),
        )
        log.debug("agents async load: prep=%.3fs", time.perf_counter() - prep_start)

        apply_start = time.perf_counter()
        # ``orphaned`` was already subtracted from ``self._dismissed_agents``
        # above; pass ``persist_dismissed=True`` so the prep-time deltas
        # (recovered + auto-dismissed) and the cleanup-time orphan removal
        # are flushed to disk in a single ``save_dismissed_agents`` call.
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
        )
        log.debug("agents async load: apply=%.3fs", time.perf_counter() - apply_start)

    def _apply_loaded_agents(
        self,
        all_agents: list[Agent],
        dismissed_from_loader: list[Agent],
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
    ) -> None:
        """Apply loaded agent data to app state (main thread only).

        Sync entry point used by :meth:`_load_agents` and tests. The async
        path (:meth:`_load_agents_async`) computes the prepared data via
        :func:`_compute_apply_loaded_agents` in a worker thread and then
        calls :meth:`_apply_loaded_agents_prepared` directly.
        """
        # Sync callers (tests and explicit _load_agents paths) own the
        # cleanup pass — the async path runs it in
        # ``_load_agents_async``.  Skipping when ``_agents_loading`` is True
        # preserves that split.
        if not self._agents_loading:
            orphaned, cleaned_dirs = _compute_loader_cleanup(
                set(self._dismissed_agents), dismissed_from_loader
            )
            if orphaned:
                self._dismissed_agents -= orphaned
            if cleaned_dirs:
                _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        else:
            orphaned = set()

        prep = _compute_apply_loaded_agents(
            all_agents,
            dismissed_from_loader,
            set(self._dismissed_agents),
            bool(self.hide_non_run_agents),
        )
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
        )

    def _apply_loaded_agents_prepared(
        self,
        prep: _PreparedApplyData,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        persist_dismissed_changes: bool,
    ) -> None:
        """UI-thread step that folds prepared filter output into ``self``.

        Updates the dismissed set with the recovered-bundle and
        auto-dismiss deltas, persists the merged set in a *single*
        :func:`save_dismissed_agents` call (replaces the old per-agent
        write loop), then drops the prepared agent list onto
        ``self._agents`` and runs the finalize pipeline. The fold filter,
        query evaluation, status overrides, registry GC, tab-bar update,
        and panel refresh all happen in :meth:`_finalize_agent_list` on
        this thread.
        """
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

        if prep.recovered_bundle_identities:
            self._dismissed_agents.update(prep.recovered_bundle_identities)
        if prep.auto_dismissed_identities:
            self._dismissed_agents.update(prep.auto_dismissed_identities)
        if persist_dismissed_changes:
            from ....dismissed_agents import save_dismissed_agents

            save_dismissed_agents(self._dismissed_agents)

        self._dismissed_agent_objects = prep.dismissed_agent_objects
        self._has_always_visible = prep.has_always_visible
        self._hidden_count = prep.hidden_count
        self._hideable_agents = prep.hideable_agents
        self._agents = prep.filtered_agents

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
        """Run the async agent refresh with loading guard.

        Defers when the user is mid-burst on j/k: the apply/finalize/render
        leg of this refresh runs on the UI thread and would block the event
        loop through the user's first navigation burst after a launch (or
        any other state-mutating action that triggered a refresh). Re-arm
        via ``set_timer`` for the gate boundary; ``_agents_refresh_scheduled``
        stays True so concurrent triggers collapse into the
        ``_agents_refresh_pending`` flag rather than scheduling duplicate
        timers.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._run_agents_async_refresh)  # type: ignore[attr-defined]
            return
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

    def _get_or_parse_agent_query(self) -> QueryExpr | None:
        """Return the parsed AST for the active agent search query."""
        return get_or_parse_agent_query(self)  # type: ignore[return-value]

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

        Thin wrapper that delegates to
        :func:`._loading_finalize.finalize_agent_list`. Tests drive this
        method directly; production callers reach it via
        :meth:`_apply_loaded_agents_prepared` and :meth:`_refilter_agents`.
        """
        finalize_agent_list(
            self,
            on_agents_tab,
            selected_identity,
            save_unfiltered=save_unfiltered,
            prior_pos=prior_pos,
        )
