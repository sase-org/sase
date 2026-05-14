"""Disk-loading entry points for :class:`AgentLoadingMixin`."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from . import _loading_helpers
from ._loading_compute import (
    _CLEANED_ARTIFACT_DIRS,
    compute_apply_loaded_agents,
    compute_loader_cleanup,
)
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...data_providers import AgentsViewport
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_loader import AgentLoadState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ExternalDismissalMergeResult:
    file_signature: tuple[int, int] | None
    on_disk_identities: set[tuple[AgentType, str, str | None]]
    new_external_identities: set[tuple[AgentType, str, str | None]]


def _agents_viewport_for_app(app: Any, *, on_agents_tab: bool) -> AgentsViewport:
    """Return a bounded daemon read window for the current Agents view."""
    from ...data_providers import AgentsViewport

    if on_agents_tab:
        current_idx = max(0, int(getattr(app, "current_idx", 0) or 0))
    else:
        current_idx = max(0, int(getattr(app, "_agents_last_idx", 0) or 0))
    size = getattr(app, "size", None)
    visible_rows = int(getattr(size, "height", 0) or 40)
    visible_rows = max(10, min(visible_rows, 80))
    start_row = max(0, current_idx - visible_rows)
    return AgentsViewport(
        start_row=start_row,
        visible_rows=visible_rows,
        prefetch_rows=visible_rows * 2,
    )


def _agents_loaded_signature(
    agents: list[Agent],
    *,
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    search_query: str,
    provider_snapshot: Any,
) -> tuple[Any, ...]:
    """Compact row signature used to skip unchanged daemon refresh rebuilds."""
    provider_key = None
    if provider_snapshot is not None:
        provider_key = (
            provider_snapshot.provider.source,
            provider_snapshot.snapshot_id,
            tuple(handle.stable_id for handle in provider_snapshot.row_handles),
            tuple(provider_snapshot.metadata.get("surfaces") or ()),
            provider_snapshot.metadata.get("query"),
            provider_snapshot.metadata.get("requested_limit"),
        )
    row_key = tuple(
        (
            agent.identity,
            agent.status,
            agent.tag,
            agent.pid,
            agent.retry_count,
            agent.retry_status,
            agent.raw_suffix,
        )
        for agent in agents
    )
    return (
        provider_key,
        row_key,
        frozenset(dismissed_snapshot),
        bool(hide_non_run_agents),
        search_query,
    )


def _can_skip_unchanged_daemon_refresh(
    app: Any,
    *,
    signature: tuple[Any, ...],
    merge_result: _ExternalDismissalMergeResult | None,
    provider_snapshot: Any,
) -> bool:
    if provider_snapshot is None or provider_snapshot.provider.source != "daemon":
        return False
    if not getattr(app, "_agents_first_load_done", False):
        return False
    if merge_result is not None and merge_result.new_external_identities:
        return False
    return signature == getattr(app, "_agents_last_loaded_signature", None)


def _resolve_load_agents_from_disk_with_state() -> Callable[..., Any]:
    """Resolve through the public facade so existing monkeypatches still work."""
    facade = sys.modules.get(f"{__package__}._loading")
    loader = getattr(
        facade,
        "load_agents_from_disk_with_state",
        _loading_helpers.load_agents_from_disk_with_state,
    )
    return cast(Callable[..., Any], loader)


def _compute_external_dismissal_merge(
    *,
    cached_signature: tuple[int, int] | None,
    cached_on_disk_identities: set[tuple[AgentType, str, str | None]],
    cache_initialized: bool,
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
) -> _ExternalDismissalMergeResult | None:
    from ....dismissed_agents import (
        dismissed_agents_file_signature,
        load_dismissed_agents,
    )

    file_signature = dismissed_agents_file_signature()
    if cache_initialized and file_signature == cached_signature:
        return None

    try:
        on_disk = load_dismissed_agents()
    except Exception:
        return None

    if cache_initialized:
        new_external = on_disk - cached_on_disk_identities
    else:
        new_external = on_disk - dismissed_snapshot

    return _ExternalDismissalMergeResult(
        file_signature=file_signature,
        on_disk_identities=set(on_disk),
        new_external_identities=new_external,
    )


class AgentLoadingDiskMixin(AgentLoadingStateMixin):
    """Methods that read agent state from disk and prepare apply snapshots."""

    def _external_dismissal_merge_result(
        self,
        dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    ) -> _ExternalDismissalMergeResult | None:
        return _compute_external_dismissal_merge(
            cached_signature=getattr(self, "_dismissed_agents_disk_signature", None),
            cached_on_disk_identities=set(
                getattr(self, "_dismissed_agents_disk_identities", set())
            ),
            cache_initialized=bool(
                getattr(self, "_dismissed_agents_disk_signature_initialized", False)
            ),
            dismissed_snapshot=dismissed_snapshot,
        )

    def _apply_external_dismissal_merge(
        self, result: _ExternalDismissalMergeResult | None
    ) -> None:
        if result is None:
            return
        self._dismissed_agents_disk_signature = result.file_signature
        self._dismissed_agents_disk_identities = set(result.on_disk_identities)
        self._dismissed_agents_disk_signature_initialized = True
        if result.new_external_identities:
            self._dismissed_agents.update(result.new_external_identities)

    def _merge_external_dismissals(self) -> None:
        """Union on-disk dismissed-agent identities into the in-memory set.

        External processes (Telegram kill, ``sase agents kill``, gchat) write
        to ``~/.sase/dismissed_agents.json`` directly via
        :func:`sase.agent.running.kill_named_agent`. Without this merge a
        long-lived TUI would never observe those entries on its next refresh
        and would re-classify the killed agent as FAILED.

        Only unions in new entries — never drops in-memory entries that
        haven't been flushed to disk yet (the optimistic kill flow updates
        memory first and persists asynchronously).
        """
        result = self._external_dismissal_merge_result(set(self._dismissed_agents))
        self._apply_external_dismissal_merge(result)

    def _load_agents(self, *, full_history: bool = False) -> None:
        """Load agents from all sources.

        Args:
            full_history: When True, force a Tier 2 (full-history) source
                scan rather than letting the artifact index gate visibility.
                Used by deliberate user actions (e.g. revive) that need to
                surface artifacts the persistent index may not yet know
                about.
        """
        from ...data_providers import (
            agents_daemon_reads_enabled,
            make_agents_data_provider,
        )
        from .._daemon_read_client import ace_daemon_read_client
        from ....changespec import find_all_changespecs_cached

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            # Off-tab rebuild: fall back to the saved identity so the next
            # tab switch back lands on the previously selected agent rather
            # than whatever drifted into ``_agents_last_idx``'s slot.
            selected_identity = getattr(self, "_agents_last_identity", None)

        self._merge_external_dismissals()
        dismissed_snapshot = set(self._dismissed_agents)
        use_daemon_provider = agents_daemon_reads_enabled()
        changespec_snapshot = (
            None if use_daemon_provider else find_all_changespecs_cached()
        )
        data_provider = (
            make_agents_data_provider(client=ace_daemon_read_client(self))
            if use_daemon_provider
            else None
        )
        search_query = getattr(self, "_agent_search_query", "") or ""
        load_result = _resolve_load_agents_from_disk_with_state()(
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history or bool(search_query),
            search_query=search_query,
            viewport=_agents_viewport_for_app(self, on_agents_tab=on_agents_tab),
            data_provider=data_provider,
        )
        self._agents_provider_snapshot = getattr(load_result, "provider_snapshot", None)
        self._agents_last_loaded_signature = _agents_loaded_signature(
            load_result.all_agents,
            dismissed_snapshot=dismissed_snapshot,
            hide_non_run_agents=bool(self.hide_non_run_agents),
            search_query=search_query,
            provider_snapshot=self._agents_provider_snapshot,
        )
        from ...repro.capture import record_agents_tab_loader_result

        record_agents_tab_loader_result(
            self,
            load_state=load_result.load_state,
            agents=load_result.all_agents,
            dismissed_from_loader=load_result.dismissed_from_loader,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            source="sync_load",
        )
        self._apply_loaded_agents(
            load_result.all_agents,
            load_result.dismissed_from_loader,
            on_agents_tab,
            selected_identity,
            load_state=load_result.load_state,
        )

    async def _load_agents_async(self, *, full_history: bool = False) -> None:
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

        from ...data_providers import (
            agents_daemon_reads_enabled,
            make_agents_data_provider,
        )
        from .._daemon_read_client import ace_daemon_read_client
        from ....changespec import find_all_changespecs_cached

        merge_result = await asyncio.to_thread(
            self._external_dismissal_merge_result, set(self._dismissed_agents)
        )
        self._apply_external_dismissal_merge(merge_result)
        dismissed_snapshot = set(self._dismissed_agents)
        use_daemon_provider = agents_daemon_reads_enabled()
        changespec_snapshot = (
            None
            if use_daemon_provider
            else await asyncio.to_thread(find_all_changespecs_cached)
        )
        data_provider = (
            make_agents_data_provider(client=ace_daemon_read_client(self))
            if use_daemon_provider
            else None
        )
        search_query = getattr(self, "_agent_search_query", "") or ""
        disk_start = time.perf_counter()
        load_result = await asyncio.to_thread(
            _resolve_load_agents_from_disk_with_state(),
            dismissed_snapshot,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history or bool(search_query),
            search_query=search_query,
            viewport=_agents_viewport_for_app(
                self, on_agents_tab=self.current_tab == "agents"
            ),
            data_provider=data_provider,
        )
        self._agents_provider_snapshot = getattr(load_result, "provider_snapshot", None)
        loaded_signature = _agents_loaded_signature(
            load_result.all_agents,
            dismissed_snapshot=dismissed_snapshot,
            hide_non_run_agents=bool(self.hide_non_run_agents),
            search_query=search_query,
            provider_snapshot=self._agents_provider_snapshot,
        )
        all_agents = load_result.all_agents
        dismissed_from_loader = load_result.dismissed_from_loader
        disk_elapsed = time.perf_counter() - disk_start
        log.debug(
            "agents async load: disk=%.3fs agents=%d dismissed=%d tier=%s source=%s complete=%s",
            disk_elapsed,
            len(all_agents),
            len(dismissed_from_loader),
            load_result.load_state.tier,
            load_result.load_state.artifact_source,
            load_result.load_state.complete_history,
        )
        if _can_skip_unchanged_daemon_refresh(
            self,
            signature=loaded_signature,
            merge_result=merge_result,
            provider_snapshot=self._agents_provider_snapshot,
        ):
            from ...util.trace import trace_event

            provider_snapshot = self._agents_provider_snapshot
            self._agent_load_state = load_result.load_state
            trace_event(
                "agents.refresh_no_change",
                provider_source="daemon",
                snapshot_id=(
                    provider_snapshot.snapshot_id
                    if provider_snapshot is not None
                    else None
                ),
            )
            return
        self._agents_last_loaded_signature = loaded_signature
        cleanup_start = time.perf_counter()
        orphaned, cleaned_dirs = await asyncio.to_thread(
            compute_loader_cleanup, dismissed_snapshot, dismissed_from_loader
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
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        from ...repro.capture import record_agents_tab_loader_result

        record_agents_tab_loader_result(
            self,
            load_state=load_result.load_state,
            agents=all_agents,
            dismissed_from_loader=dismissed_from_loader,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            source="async_load",
        )

        prep_start = time.perf_counter()
        # Bind the worker function to a local so ``to_thread`` doesn't see
        # the bare module-level reference on its own line — pyvision's
        # multi-line-import heuristic flags ``<name>,`` as an import
        # continuation, which would force this private helper public for
        # no semantic reason.
        prep_worker = compute_apply_loaded_agents
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
            load_state=load_result.load_state,
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
        load_state: AgentLoadState | None = None,
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
            orphaned, cleaned_dirs = compute_loader_cleanup(
                set(self._dismissed_agents), dismissed_from_loader
            )
            if orphaned:
                self._dismissed_agents -= orphaned
            if cleaned_dirs:
                _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        else:
            orphaned = set()

        prep = compute_apply_loaded_agents(
            all_agents,
            dismissed_from_loader,
            set(self._dismissed_agents),
            bool(self.hide_non_run_agents),
        )
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_state,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
        )
