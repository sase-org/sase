"""Auto-refresh timer handling for sase's TUI event refreshes."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

from .._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ...util.pump_tasks import spawn_pump_free_task
from ._auto_refresh_surfaces import EventAutoRefreshSurfacesMixin

log = logging.getLogger(__name__)

_CAPACITY_REPORT_POLL_SECONDS = 10.0
_CAPACITY_GAUGE_TELEMETRY_MIN_INTERVAL_SECONDS = 2.0
_CAPACITY_DRIFT_TELEMETRY_MIN_INTERVAL_SECONDS = 60.0


class _CapacityReportFeedMixin:
    """Poll capacity tokens and compute reports away from Textual's pump."""

    def _start_machine_capacity_report_feed(self) -> None:
        """Start the 10-second capacity/liveness feed after first paint."""
        if getattr(self, "_machine_capacity_feed_timer", None) is not None:
            return
        try:
            self._machine_capacity_feed_timer = self.set_interval(  # type: ignore[attr-defined]
                _CAPACITY_REPORT_POLL_SECONDS,
                self._on_machine_capacity_feed_tick,
                name="machine-capacity-report",
            )
        except Exception:
            log.exception("Failed to start machine capacity report timer")
            return
        self._on_machine_capacity_feed_tick()

    def _stop_machine_capacity_report_feed(self) -> None:
        """Stop the report timer; pump-free tasks are cancelled by lifecycle."""
        timer = getattr(self, "_machine_capacity_feed_timer", None)
        self._machine_capacity_feed_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                log.debug("Failed to stop capacity report timer", exc_info=True)

    def _probe_machine_capacity_surface_token(self) -> object:
        """Stat only the admission token and runner-limit override file."""
        probe = getattr(self, "_machine_capacity_token_probe", None)
        if callable(probe):
            return probe()
        from sase.config.runner_limit_override import runner_limit_override_path
        from sase.core.agent_hold_facade import agent_hold_store_path
        from sase.core.paths import sase_home

        from ._surface_tokens import probe_runner_capacity_token

        return probe_runner_capacity_token(
            sase_home() / "runner_slots.token",
            runner_limit_override_path(),
            agent_hold_store_path(),
        )

    def _on_machine_capacity_feed_tick(self) -> None:
        """Thin timer callback: probe token metadata, then spawn report work."""
        try:
            token = self._probe_machine_capacity_surface_token()
        except Exception:
            log.debug("Capacity token probe failed", exc_info=True)
            token = None
        previous = getattr(self, "_machine_capacity_observed_token", None)
        self._machine_capacity_observed_token = token
        token_changed = previous is None or token != previous
        now = time.monotonic()
        last_report = float(getattr(self, "_machine_capacity_report_mono", 0.0))
        liveness_due = now - last_report >= _CAPACITY_REPORT_POLL_SECONDS
        if token_changed or liveness_due:
            self._request_machine_capacity_report_refresh(
                source="token_change" if token_changed else "liveness_poll"
            )

    def _request_machine_capacity_report_refresh(self, *, source: str) -> None:
        """Coalesce report requests and retain one trailing refresh."""
        del source
        generation = int(getattr(self, "_machine_capacity_refresh_generation", 0)) + 1
        self._machine_capacity_refresh_generation = generation
        if getattr(self, "_machine_capacity_refresh_running", False) or getattr(
            self, "_machine_capacity_refresh_scheduled", False
        ):
            self._machine_capacity_refresh_pending = True
            return
        self._machine_capacity_refresh_scheduled = True
        task = spawn_pump_free_task(
            self,
            self._run_machine_capacity_report_refresh(generation=generation),
            name="sase-machine-capacity-report",
            registry_attr="_machine_capacity_feed_tasks",
        )
        if task is None:
            self._machine_capacity_refresh_scheduled = False

    async def _run_machine_capacity_report_refresh(self, *, generation: int) -> None:
        """Compute and publish one report, then service a coalesced request."""
        self._machine_capacity_refresh_scheduled = False
        if getattr(self, "_machine_capacity_refresh_running", False):
            self._machine_capacity_refresh_pending = True
            return
        self._machine_capacity_refresh_running = True
        try:
            report = await asyncio.to_thread(self._build_machine_capacity_report)
            if generation != int(
                getattr(self, "_machine_capacity_refresh_generation", 0)
            ):
                return
            self._install_machine_capacity_report(report)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Machine capacity report refresh failed")
        finally:
            self._machine_capacity_refresh_running = False
            if getattr(self, "_machine_capacity_refresh_pending", False):
                self._machine_capacity_refresh_pending = False
                self._request_machine_capacity_report_refresh(source="coalesced")

    def _build_machine_capacity_report(self) -> Any:
        """Build the report; tests may inject a filesystem-free source."""
        source = getattr(self, "_machine_capacity_report_source", None)
        if callable(source):
            return source()
        from sase.core.runner_slots import machine_capacity_report

        return machine_capacity_report()

    def _install_machine_capacity_report(self, report: Any) -> None:
        """Make a completed report authoritative and refresh cached rows."""
        from ...models.agent_runner_slots import refresh_runner_slot_context

        self._machine_capacity_report = report
        self._machine_capacity_report_generation = (
            int(getattr(self, "_machine_capacity_report_generation", 0)) + 1
        )
        self._machine_capacity_report_mono = time.monotonic()
        report_capacity = refresh_runner_slot_context(
            [],
            raw_snapshot=report.raw_snapshot,
            report=report,
        )
        self._agent_runner_capacity = report_capacity
        self._agent_info_metrics_cache = None
        update_info = getattr(self, "_update_agents_info_panel", None)
        if getattr(self, "current_tab", None) == "agents" and callable(update_info):
            update_info()

        bump = getattr(self, "_bump_agents_capacity_generation", None)
        if callable(bump):
            bump()
        if getattr(self, "_agents_first_load_done", False):
            schedule = getattr(
                self, "_schedule_agents_capacity_refresh_from_roster", None
            )
            if callable(schedule):
                schedule(source="authoritative_capacity_report")

        self._record_capacity_gauge_telemetry(report, report_capacity)
        self._observe_machine_capacity_drift(source="report")

    def _record_capacity_gauge_telemetry(
        self,
        report: Any,
        capacity: Any,
    ) -> None:
        """Record changed gauge values, coalesced and rate-limited."""
        owner_keys = tuple(capacity.claim_owner_keys)
        signature = (
            capacity.source,
            capacity.occupied_capacity,
            capacity.effective_limit,
            owner_keys,
            capacity.accounting_valid,
        )
        record = {
            "event": "capacity_gauge",
            "timestamp": time.time(),
            "token": report.token,
            "occupied": capacity.known_occupied_capacity,
            "limit": capacity.effective_limit,
            "claim_owner_keys": list(owner_keys),
            "validity": capacity.accounting_valid,
            "source": capacity.source,
        }
        if signature == getattr(self, "_capacity_gauge_telemetry_signature", None):
            return
        now = time.monotonic()
        last = float(getattr(self, "_capacity_gauge_telemetry_mono", 0.0))
        if now - last < _CAPACITY_GAUGE_TELEMETRY_MIN_INTERVAL_SECONDS:
            return
        self._capacity_gauge_telemetry_signature = signature
        self._capacity_gauge_telemetry_mono = now
        self._schedule_capacity_telemetry_write(record)

    def _observe_machine_capacity_drift(self, *, source: str) -> None:
        """Compare the roster estimate to the report as a drift witness."""
        del source
        report = getattr(self, "_machine_capacity_report", None)
        estimate = getattr(self, "_agent_runner_capacity_estimate", None)
        if report is None or estimate is None or estimate.occupied_capacity is None:
            return
        if getattr(report, "accounting_valid", False) is not True:
            return
        report_capacity = getattr(report, "occupied_capacity", None)
        if report_capacity is None or not math.isfinite(float(report_capacity)):
            return
        report_generation = int(getattr(self, "_machine_capacity_report_generation", 0))
        estimate_generation = int(
            getattr(self, "_agents_capacity_estimate_generation", 0)
        )
        comparison = (report_generation, estimate_generation)
        if comparison == getattr(self, "_capacity_drift_last_comparison", None):
            return
        self._capacity_drift_last_comparison = comparison

        roster_dirs = set(estimate.claim_artifact_dirs)
        report_dirs = set(_report_claim_artifact_dirs(getattr(report, "claims", ())))
        differing_dirs = tuple(sorted(roster_dirs ^ report_dirs))
        disagrees = not math.isclose(
            float(estimate.occupied_capacity),
            float(report_capacity),
            rel_tol=0.0,
            abs_tol=1e-9,
        ) or bool(differing_dirs)
        if not disagrees:
            self._capacity_drift_consecutive = 0
            self._capacity_drift_signature = None
            return

        signature = (
            float(estimate.occupied_capacity),
            float(report_capacity),
            differing_dirs,
        )
        self._capacity_drift_consecutive = (
            int(getattr(self, "_capacity_drift_consecutive", 0)) + 1
        )
        if self._capacity_drift_consecutive < 2:
            return
        now = time.monotonic()
        last = float(getattr(self, "_capacity_drift_telemetry_mono", 0.0))
        if now - last < _CAPACITY_DRIFT_TELEMETRY_MIN_INTERVAL_SECONDS:
            return
        self._capacity_drift_signature = signature
        self._capacity_drift_telemetry_mono = now
        self._schedule_capacity_telemetry_write(
            {
                "event": "capacity_drift",
                "timestamp": time.time(),
                "token": report.token,
                "roster_occupied": float(estimate.occupied_capacity),
                "report_occupied": float(report_capacity),
                "differing_artifact_dirs": list(differing_dirs),
            }
        )

    def _schedule_capacity_telemetry_write(self, record: dict[str, Any]) -> None:
        async def _write() -> None:
            from sase.logs.tui_telemetry import log_tui_agent_load

            await asyncio.to_thread(log_tui_agent_load, record)

        spawn_pump_free_task(
            self,
            _write(),
            name="sase-capacity-telemetry",
            registry_attr="_capacity_telemetry_tasks",
        )


def _report_claim_artifact_dirs(claims: object) -> tuple[str, ...]:
    if not isinstance(claims, (list, tuple)):
        return ()
    dirs: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        owner = claim.get("owner_artifact_dir")
        if isinstance(owner, str) and owner:
            dirs.add(owner)
        artifact_dirs = claim.get("artifact_dirs")
        if isinstance(artifact_dirs, (list, tuple)):
            dirs.update(item for item in artifact_dirs if isinstance(item, str))
    return tuple(sorted(dirs))


class EventAutoRefreshMixin(_CapacityReportFeedMixin, EventAutoRefreshSurfacesMixin):
    """Mixin for auto-refresh timers and lightweight live-file updates."""

    def _on_auto_refresh(self) -> None:
        """Timer-facing sync callback that launches a pump-free refresh.

        When the user is mid-burst on j/k the refresh defers itself for the
        remainder of the navigation window plus a small overshoot.  A new
        ``set_timer`` call schedules a single retry; if the user is *still*
        navigating when that fires, the same gate will defer it again.

        When the inotify watcher is active each surface's refresh is gated
        on its dirty flag; flags clear after the refresh runs. Stat-only
        token probes additionally skip unchanged surfaces. Every sanity
        interval we ignore those gates and run a full reconcile to recover
        from missed events.
        """
        self._countdown_remaining = self.refresh_interval
        self._startup_auto_refresh_tick_count = (
            getattr(self, "_startup_auto_refresh_tick_count", 0) + 1
        )
        if self._nav_gate.is_navigating():
            if getattr(self, "_auto_refresh_deferred", False):
                return
            self._auto_refresh_deferred = True
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._retry_auto_refresh)  # type: ignore[attr-defined]
            return
        if self._prompt_input_active():
            return
        from ..agents._archive_controller import schedule_archive_idle_tick

        schedule_archive_idle_tick(self)
        if getattr(self, "_auto_refresh_running", False):
            self._auto_refresh_pending = True
            return
        if getattr(self, "_auto_refresh_scheduled", False):
            return
        self._auto_refresh_scheduled = True
        self._spawn_auto_refresh_task()

    def _retry_auto_refresh(self) -> None:
        """Navigation-gate timer callback that only invokes the sync spawner."""
        self._auto_refresh_deferred = False
        self._on_auto_refresh()

    def _spawn_auto_refresh_task(self) -> None:
        """Run auto-refresh without making Textual's message pump await it."""
        task = spawn_pump_free_task(
            self,
            self._run_auto_refresh(),
            name="sase-auto-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._auto_refresh_scheduled = False

    async def _run_auto_refresh(self) -> None:
        """Run one guarded refresh and coalesce a trailing timer tick."""
        self._auto_refresh_scheduled = False
        if getattr(self, "_auto_refresh_running", False):
            self._auto_refresh_pending = True
            return
        self._auto_refresh_running = True
        try:
            await self._run_auto_refresh_body()
        finally:
            self._auto_refresh_running = False
            if getattr(self, "_auto_refresh_pending", False):
                self._auto_refresh_pending = False
                self._on_auto_refresh()

    def action_debug_leak_snapshot(self) -> None:
        """One-shot leak snapshot keybind gated by ``SASE_ACE_DEBUG_LEAKS=1``.

        Logs the snapshot and surfaces the headline counts via the
        Textual notification toast so the snapshot is visible without
        digging through the log file.
        """
        if not debug_leaks_enabled():
            return
        snapshot = log_leak_snapshot(self, source="keybind")
        message = (
            f"artifact_cache={snapshot['artifact_page_cache']} "
            f"watches={snapshot['fs_watcher_watches']} "
            f"dismissed={snapshot['dismissed_agent_objects']} "
            f"agents={snapshot['agents_with_children']} "
            f"tasks={snapshot['pending_asyncio_tasks']} "
            f"fds={snapshot['open_fds']}"
        )
        try:
            self.notify(message, title="leak snapshot", timeout=10)  # type: ignore[attr-defined]
        except Exception:
            pass
