"""Pump-safe ACE status checks and tracked agents-repository sync actions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from sase.agents_sync import (
    get_agents_sync_status,
    integrate_cached_agent_updates,
    sync_agents,
)
from sase.agents_sync.models import (
    CachedIntegrationResult,
    CapturedIncomingHood,
    SyncOutcome,
    SyncStatusSnapshot,
)

from ..agents_sync_format import (
    agents_sync_outcome_line,
    cached_agents_result_line,
    summarize_cached_agents_results,
    summarize_agents_sync_outcomes,
)
from ._agents_sync_config import (
    DEFAULT_AGENTS_SYNC_CHECK_INTERVAL_SECONDS,
    DEFAULT_AGENTS_SYNC_RECOMPUTE_INTERVAL_SECONDS,
)
from .task_actions import TrackedTaskCompletion, TrackedTaskResult
from ..util.shutdown import is_shutdown_requested

if TYPE_CHECKING:
    from textual.timer import Timer

    from ..task_subprocess import TaskReporter

log = logging.getLogger(__name__)

_AGENTS_SYNC_TIMER_NAME = "agents-sync-check"


@dataclass(frozen=True, slots=True)
class _AgentsSyncStatusCheckResult:
    snapshot: SyncStatusSnapshot | None
    recomputed: bool
    completed_mono: float


class AgentsSyncActionsMixin:
    """Own the ACE agents-sync cadence, indicator, and manual mutation."""

    _agents_sync_check_interval_seconds: float
    _agents_sync_recompute_interval_seconds: float
    _agents_sync_indicator_enabled: bool
    _agents_sync_check_timer: Timer | None
    _agents_sync_check_in_flight: bool
    _agents_sync_revalidation_pending: bool
    _agents_sync_last_status: SyncStatusSnapshot | None
    _agents_sync_last_recompute_mono: float

    def _schedule_startup_agents_sync_check(self) -> None:
        """Register one timer and start the first post-paint status worker."""
        if not self._agents_sync_indicator_enabled:
            self._set_agents_sync_indicator_status(SyncStatusSnapshot(0.0))
            return
        self._start_periodic_agents_sync_checks()
        self._schedule_agents_sync_status_check()

    def _start_periodic_agents_sync_checks(self) -> None:
        """Register the configured timer once without performing slow work."""
        if self._agents_sync_check_timer is not None:
            return
        try:
            self._agents_sync_check_timer = self.set_interval(  # type: ignore[attr-defined]
                self._agents_sync_check_interval_seconds,
                self._on_periodic_agents_sync_check,
                name=_AGENTS_SYNC_TIMER_NAME,
            )
        except Exception:
            log.debug("Failed to start periodic agents-sync checks", exc_info=True)

    def _on_periodic_agents_sync_check(self) -> None:
        """Keep the Textual timer callback synchronous and scheduling-only."""
        self._schedule_agents_sync_status_check()

    def _schedule_agents_sync_status_check(
        self,
        *,
        recompute: bool | None = None,
    ) -> None:
        """Schedule one guarded status worker, coalescing a trailing revalidation."""
        if self._agents_sync_check_in_flight:
            if recompute is False:
                self._agents_sync_revalidation_pending = True
            return

        if recompute is None:
            now_mono = time.monotonic()
            recompute = (
                self._agents_sync_last_recompute_mono <= 0.0
                or now_mono - self._agents_sync_last_recompute_mono
                >= self._agents_sync_recompute_interval_seconds
            )
        self._agents_sync_check_in_flight = True
        worker_fn = partial(self._run_agents_sync_status_check, recompute=recompute)
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, worker_fn),
                name="agents-sync-status-check",
                thread=True,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            self._agents_sync_check_in_flight = False
            log.debug("Failed to schedule agents-sync status check", exc_info=True)

    def _schedule_agents_sync_indicator_revalidation(self) -> None:
        """Request the shared no-network path after a completed mutation."""
        self._schedule_agents_sync_status_check(recompute=False)

    def _run_agents_sync_status_check(self, *, recompute: bool) -> None:
        """Compute status in a worker thread and marshal completion to the UI."""
        snapshot: SyncStatusSnapshot | None = None
        try:
            snapshot = get_agents_sync_status(
                refresh=recompute,
                revalidate_only=not recompute,
                shutdown_requested=is_shutdown_requested,
            )
        except Exception:
            log.debug("Agents-sync status check failed", exc_info=True)
        result = _AgentsSyncStatusCheckResult(
            snapshot=snapshot,
            recomputed=recompute,
            completed_mono=time.monotonic(),
        )
        try:
            self.call_from_thread(  # type: ignore[attr-defined]
                self._complete_agents_sync_status_check,
                result,
            )
        except Exception:
            self._agents_sync_check_in_flight = False
            log.debug("Failed to apply agents-sync status check", exc_info=True)

    def _complete_agents_sync_status_check(
        self,
        result: _AgentsSyncStatusCheckResult,
    ) -> None:
        """Apply worker state and release the overlap guard on the UI thread."""
        if result.recomputed:
            self._agents_sync_last_recompute_mono = result.completed_mono
        try:
            if result.snapshot is not None:
                self._agents_sync_last_status = result.snapshot
                self._set_agents_sync_indicator_status(result.snapshot)
        finally:
            self._agents_sync_check_in_flight = False

        if self._agents_sync_revalidation_pending:
            self._agents_sync_revalidation_pending = False
            self._schedule_agents_sync_status_check(recompute=False)

    def _set_agents_sync_indicator_status(
        self,
        snapshot: SyncStatusSnapshot,
    ) -> None:
        """Apply an immutable projection to the mounted indicator only."""
        from ..widgets import AgentsSyncIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#agents-sync-indicator",
                AgentsSyncIndicator,
            )
        except Exception:
            return
        indicator.set_status(
            snapshot
            if self._agents_sync_indicator_enabled
            else SyncStatusSnapshot(snapshot.checked_at)
        )

    def action_sync_agents(self) -> None:
        """Submit synchronization of every enabled agents repo as a tracked task."""

        def task(
            reporter: TaskReporter,
        ) -> TrackedTaskResult[tuple[SyncOutcome, ...]]:
            reporter.phase("Synchronizing agents repositories")
            outcomes = sync_agents()
            reporter.section("Agents repository results")
            for outcome in outcomes:
                reporter.log(agents_sync_outcome_line(outcome), stream="result")
            message = f"Agents repos: {summarize_agents_sync_outcomes(outcomes)}"
            failed = any(outcome.error for outcome in outcomes)
            return TrackedTaskResult(
                success=not failed,
                message=message,
                payload=outcomes,
                error=message if failed else None,
            )

        def on_complete(
            _completion: TrackedTaskCompletion[tuple[SyncOutcome, ...]],
        ) -> None:
            self._schedule_agents_sync_indicator_revalidation()
            self._schedule_agents_refresh_after_sync(source="agents_full_sync")

        submit = getattr(self, "_submit_tracked_task", None)
        if not callable(submit):
            return
        submit(
            "agents-sync",
            "agents repositories",
            "",
            task,
            display_name="sync agents repositories",
            dedup_key="agents-sync",
            exclusive_scopes=("agents-sync",),
            duplicate_message="An agents-repository synchronization is already running.",
            on_complete=on_complete,
            reload_on_complete=False,
        )

    def action_integrate_cached_agents(self) -> None:
        """Import exactly the cached hoods currently represented by the badge."""
        from ..widgets import AgentsSyncIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#agents-sync-indicator",
                AgentsSyncIndicator,
            )
        except Exception:
            return
        captured_items: tuple[CapturedIncomingHood, ...] = indicator.pending_updates
        if not captured_items:
            return

        def task(
            reporter: TaskReporter,
        ) -> TrackedTaskResult[tuple[CachedIntegrationResult, ...]]:
            reporter.phase("Importing cached incoming agent hoods")
            results = integrate_cached_agent_updates(captured_items)
            reporter.section("Cached incoming hood results")
            for result in results:
                reporter.log(cached_agents_result_line(result), stream="result")
            message = "Cached agents: " + summarize_cached_agents_results(results)
            failed = any(not result.ok for result in results)
            return TrackedTaskResult(
                success=not failed,
                message=message,
                payload=results,
                error=message if failed else None,
            )

        def on_complete(
            _completion: TrackedTaskCompletion[tuple[CachedIntegrationResult, ...]],
        ) -> None:
            self._schedule_agents_sync_indicator_revalidation()
            self._schedule_agents_refresh_after_sync(source="agents_cached_integration")

        submit = getattr(self, "_submit_tracked_task", None)
        if not callable(submit):
            return
        submit(
            "agents-cached-integration",
            "cached incoming agent hoods",
            "",
            task,
            display_name="import cached incoming hoods",
            dedup_key="agents-sync",
            exclusive_scopes=("agents-sync",),
            duplicate_message="An agents-repository synchronization is already running.",
            on_complete=on_complete,
            reload_on_complete=False,
        )

    def _schedule_agents_refresh_after_sync(self, *, source: str) -> None:
        """Use the existing coalesced agent-list reload after sync mutations."""
        refresh = getattr(self, "_schedule_agents_async_refresh", None)
        if callable(refresh):
            refresh(source=source)


def initialize_agents_sync_state(self: Any) -> None:
    """Initialize scheduler state before merged configuration is loaded."""
    self._agents_sync_check_interval_seconds = (
        DEFAULT_AGENTS_SYNC_CHECK_INTERVAL_SECONDS
    )
    self._agents_sync_recompute_interval_seconds = (
        DEFAULT_AGENTS_SYNC_RECOMPUTE_INTERVAL_SECONDS
    )
    self._agents_sync_indicator_enabled = True
    self._agents_sync_check_timer = None
    self._agents_sync_check_in_flight = False
    self._agents_sync_revalidation_pending = False
    self._agents_sync_last_status = None
    self._agents_sync_last_recompute_mono = 0.0


__all__ = ["AgentsSyncActionsMixin", "initialize_agents_sync_state"]
