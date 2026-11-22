"""Publish and telemetry for the machine-capacity report feed."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import is_enabled as tui_trace_enabled, tui_trace
from ._auto_refresh_capacity_probe import EventAutoRefreshCapacityProbeMixin
from ._auto_refresh_capacity_signatures import (
    CAPACITY_REPORT_POLL_SECONDS,
    capacity_override_fingerprint,
    freeze_capacity_value,
)

log = logging.getLogger(__name__)

_CAPACITY_GAUGE_TELEMETRY_MIN_INTERVAL_SECONDS = 2.0
_CAPACITY_DRIFT_TELEMETRY_MIN_INTERVAL_SECONDS = 60.0


def _capacity_report_visible_signature(report: Any) -> Any:
    """Return the visible capacity signature, excluding computation times.

    Covers claims, queues (waiters), holds-derived accounting, effective
    limits, diagnostic/validity state, record inputs and inspector-visible
    fields. Excludes ``computed_at``, ``scanned_at`` and ``captured_at``.
    """
    limit = getattr(report, "limit", None)
    if limit is not None:
        configured = getattr(limit, "configured_limit", None)
        override = getattr(limit, "temporary_override", None)
        limit_fp = capacity_override_fingerprint(configured, override)
    else:
        limit_fp = (getattr(report, "effective_limit", None), None, None)
    return (
        getattr(report, "machine", None),
        getattr(report, "effective_limit", None),
        limit_fp,
        getattr(report, "occupied_capacity", None),
        getattr(report, "occupied_lanes", None),
        getattr(report, "over_limit", None),
        freeze_capacity_value(getattr(report, "claims", ())),
        freeze_capacity_value(getattr(report, "waiters", ())),
        freeze_capacity_value(getattr(report, "accounting", ())),
        freeze_capacity_value(getattr(report, "diagnostics", ())),
        bool(getattr(report, "accounting_valid", False)),
        bool(getattr(report, "accounting_available", False)),
        bool(getattr(report, "scan_current", False)),
        freeze_capacity_value(getattr(report, "record_inputs", ())),
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


class EventAutoRefreshCapacityMixin(EventAutoRefreshCapacityProbeMixin):
    """Mixin for coalesced capacity-report refresh, install, and telemetry."""

    def _start_machine_capacity_report_feed(self) -> None:
        """Start the 10-second capacity/liveness feed after first paint."""
        if getattr(self, "_machine_capacity_feed_timer", None) is not None:
            return
        try:
            self._machine_capacity_feed_timer = self.set_interval(  # type: ignore[attr-defined]
                CAPACITY_REPORT_POLL_SECONDS,
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

    def _on_machine_capacity_feed_tick(self) -> None:
        """Thin timer callback: hand work to the pump-free task (no I/O)."""
        self._request_machine_capacity_report_refresh(source="capacity_tick")

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

    def _capacity_inspector_open(self) -> bool:
        """Return True when the capacity inspector modal is open."""
        try:
            screen = getattr(self, "screen", None)
            update = getattr(screen, "update_capacity_report", None)
            return callable(update)
        except Exception:
            return False

    async def _cache_capacity_inputs_for_revalidation(
        self,
        visible_signature: Any,
    ) -> None:
        """Cache holds/override/liveness/visible for the next 10s check.

        Reuses the probe's snapshot when the current probe already fetched
        it; otherwise fetches fresh off-thread (token-change path).
        """
        snapshot = getattr(self, "_machine_capacity_probe_snapshot", None)
        # Clear immediately so a stale snapshot never leaks into the next run.
        try:
            if hasattr(self, "_machine_capacity_probe_snapshot"):
                delattr(self, "_machine_capacity_probe_snapshot")
        except Exception:
            pass
        if (
            isinstance(snapshot, tuple)
            and len(snapshot) == 3
            and snapshot[0] is not None
            and snapshot[1] is not None
            and snapshot[2] is not None
        ):
            holds, override_fp, liveness = snapshot
        else:
            try:
                now_wall = time.time()
                (
                    holds,
                    override_fp,
                    liveness,
                ) = await self._fetch_capacity_revalidation_snapshot(now_wall)
            except Exception:
                log.debug("Capacity cache refresh failed", exc_info=True)
                return
            if holds is None or override_fp is None or liveness is None:
                return
        self._machine_capacity_last_holds_signature = holds
        self._machine_capacity_last_override_signature = override_fp
        self._machine_capacity_last_liveness_signature = liveness
        self._machine_capacity_last_visible_signature = visible_signature

    async def _run_machine_capacity_report_refresh(self, *, generation: int) -> None:
        """Compute and publish one report, then service a coalesced request."""
        with tui_trace("capacity.report_refresh") as telemetry:
            trace_enabled = tui_trace_enabled()
            if trace_enabled:
                telemetry.update(
                    {
                        "probe_count": 0,
                        "build_count": 0,
                        "install_count": 0,
                        "outcome": "not_started",
                    }
                )
            await self._run_machine_capacity_report_refresh_body(
                generation=generation,
                telemetry=telemetry if trace_enabled else None,
            )

    async def _run_machine_capacity_report_refresh_body(
        self,
        *,
        generation: int,
        telemetry: dict[str, Any] | None,
    ) -> None:
        """Run a measured report pass while preserving its coalescing guard."""
        self._machine_capacity_refresh_scheduled = False
        if getattr(self, "_machine_capacity_refresh_running", False):
            self._machine_capacity_refresh_pending = True
            if telemetry is not None:
                telemetry["outcome"] = "coalesced"
            return
        self._machine_capacity_refresh_running = True
        try:
            if telemetry is None:
                due = await self._probe_machine_capacity_refresh_due()
            else:
                telemetry["probe_count"] = 1
                due = await self._probe_machine_capacity_refresh_due(
                    telemetry=telemetry
                )
            if not due:
                if telemetry is not None:
                    telemetry["outcome"] = "skipped_unchanged"
                return
            if telemetry is not None:
                telemetry["build_count"] = 1
            report = await asyncio.to_thread(self._build_machine_capacity_report)
            if generation != int(
                getattr(self, "_machine_capacity_refresh_generation", 0)
            ):
                if telemetry is not None:
                    telemetry["outcome"] = "stale_generation"
                return
            new_visible = _capacity_report_visible_signature(report)
            last_visible = getattr(
                self, "_machine_capacity_last_visible_signature", None
            )
            if (
                last_visible is not None
                and new_visible == last_visible
                and not self._capacity_inspector_open()
            ):
                # Unchanged publication: refresh revalidation state without
                # invalidating metrics, repainting rows, or scheduling work.
                self._machine_capacity_report_mono = time.monotonic()
                await self._cache_capacity_inputs_for_revalidation(new_visible)
                if telemetry is not None:
                    telemetry["outcome"] = "read_unchanged"
                return
            if telemetry is not None:
                telemetry["install_count"] = 1
            self._install_machine_capacity_report(report)
            await self._cache_capacity_inputs_for_revalidation(new_visible)
            if telemetry is not None:
                telemetry["outcome"] = "applied_changed"
        except asyncio.CancelledError:
            if telemetry is not None:
                telemetry["outcome"] = "cancelled"
            raise
        except Exception:
            if telemetry is not None:
                telemetry["outcome"] = "error"
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
        self._refresh_open_capacity_inspector(report)

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

    def _refresh_open_capacity_inspector(self, report: Any) -> None:
        """Refresh the inspector from a report already installed by this feed."""
        screen = getattr(self, "screen", None)
        update = getattr(screen, "update_capacity_report", None)
        if not callable(update):
            return
        try:
            from ...widgets import AgentLoadIndicator

            indicator = self.query_one(  # type: ignore[attr-defined]
                "#agent-load-indicator",
                AgentLoadIndicator,
            )
            running_nodes = indicator.running_nodes
        except Exception:
            running_nodes = None
        update(report, running_nodes=running_nodes)

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
