"""Tick orchestration half of the lumberjack loop."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.core.time import get_timezone
from sase.telemetry.metrics import AXE_CYCLE_DURATION, AXE_CYCLES

from .chop_lifecycle import finalize_launched_chop_runs
from .config import ChopConfig
from .maintenance import clear_stale_maintenance, read_maintenance
from .routine_cadence import persists_cadence, write_last_tick_at
from .state import write_chop_timestamps
from .tick_context import routine_reads_tick_patches
from ._lumberjack_shared import LumberjackBase, LumberjackChopResult


class LumberjackTickMixin(LumberjackBase):
    """Runs one scheduling tick across the eligible chops."""

    def _run_tick(self) -> None:
        """Execute one tick: refresh patches, serialize context, invoke chop scripts."""
        if self._held_for_code_swap():
            return
        tick_started_at = time.time()
        from sase.project_display_names import refresh_project_display_snapshot

        try:
            refresh_project_display_snapshot()
        except Exception:  # noqa: BLE001 - log keeps stale labels; next tick retries.
            pass
        _tick_start = time.monotonic()
        recovery_results = self._recover_pending_batches()
        # The recovery entry point owns persistence and notices; retain the
        # returned outcomes here as well so routine logs show normal owner
        # holds, per-member conflicts, and failures without suppressing them.
        for result in recovery_results:
            if result.kind == "blocked":
                self._log(
                    f"Chop batch recovery held for {result.job} run {result.batch_id}: "
                    f"{result.reason or result.blocked}",
                    style="yellow",
                )
            elif result.kind == "cancelled":
                self._log(
                    f"Chop batch {result.batch_id} for {result.job} was cancelled"
                )
        recovery_held_jobs = {
            result.job
            for result in recovery_results
            if result.kind == "blocked" or result.blocked or result.paused
        }
        finalized_actions = finalize_launched_chop_runs(
            self.name,
            self.config.chop_names,
        )
        if finalized_actions:
            self._log(f"Finalized {finalized_actions} job action lifecycle(s)")
        stale_marker = clear_stale_maintenance()
        if stale_marker is not None:
            self._log(
                "Cleared stale axe maintenance marker "
                f"(reason: {stale_marker.get('reason', 'unknown')})"
            )

        maintenance = read_maintenance()
        if maintenance is not None:
            tick_duration = time.monotonic() - _tick_start
            self._log(
                "Skipping tick during axe maintenance "
                f"(reason: {maintenance.get('reason')}, "
                f"pid: {maintenance.get('pid')})"
            )
            self._metrics.cycles_run += 1
            self._record_tick_load(spawns=0, skipped=0, no_ops=0)
            self._update_status()
            self._update_metrics()
            AXE_CYCLES.labels(cycle_type=self.name).inc()
            AXE_CYCLE_DURATION.labels(cycle_type=self.name).observe(tick_duration)
            return

        # Serialize the job context, plus Patches only when a job reads them.
        tick_dir = self._state_dir / "tick"
        if not best_effort_test_state_write_allowed(
            tick_dir, category="axe-chop-state"
        ):
            return
        tick_dir.mkdir(parents=True, exist_ok=True)
        if persists_cadence(self.config.interval):
            write_last_tick_at(
                self.name,
                started_at=tick_started_at,
                interval=self.config.interval,
            )
        context_file = self._tick_context.write(
            self._build_chop_context,
            include_patches=routine_reads_tick_patches(self.config.chops),
        )

        now = datetime.now(get_timezone())

        # Filter eligible chops by their optional cadence.
        eligible_chops: list[ChopConfig] = []
        run_every_skips = 0
        recovery_skips = 0
        for chop in self.config.chops:
            if not chop.enabled:
                continue
            if chop.name in recovery_held_jobs:
                recovery_skips += 1
                continue
            if chop.run_every is not None:
                last_run = self._chop_timestamps.get(chop.name)
                if last_run is not None:
                    elapsed = (now - last_run).total_seconds()
                    if elapsed < chop.run_every:
                        run_every_skips += 1
                        continue
            eligible_chops.append(chop)

        # Script chops within one lumberjack tick run concurrently, at most
        # ``max_concurrent_jobs`` at once, longest-known first. A shutdown
        # request prevents any new worker from starting (queued chops return
        # a shutdown skip); the current dispatch is allowed to acknowledge at
        # its next boundary.
        results: list[LumberjackChopResult] = []
        max_workers = max(1, self.config.max_concurrent_jobs)
        if len(eligible_chops) > max_workers:
            eligible_chops = self._dispatch_order(eligible_chops)
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"routine-{self.name}",
        ) as executor:
            futures = {}
            for chop in eligible_chops:
                if self._stop_signal.stop_requested() or not self._running:
                    break
                futures[executor.submit(self._run_single_chop, chop, context_file)] = (
                    chop
                )
            for future in as_completed(futures):
                results.append(future.result())

        # Aggregate results in the main thread
        timestamps_dirty = False
        tick_spawns = 0
        tick_no_ops = 0
        tick_skipped = run_every_skips
        if run_every_skips:
            self._metrics.record_skips("run_every", run_every_skips)
        if recovery_skips:
            self._metrics.record_skips("recovery_hold", recovery_skips)
            tick_skipped += recovery_skips
        for result in results:
            for line in result.log_lines:
                self._log(line)
            if result.error is not None:
                self._handle_error(
                    result.chop_name,
                    result.error,
                    result.traceback,
                    result.subprocess_diagnostic,
                )
            if result.executed:
                self._metrics.chops_spawned += 1
                tick_spawns += 1
                if result.no_op:
                    self._metrics.chops_no_op += 1
                    tick_no_ops += 1
            if result.executed and result.success:
                self._metrics.chops_executed += 1
            if result.skip_reason:
                self._metrics.record_skips(result.skip_reason)
                tick_skipped += 1
            if result.update_timestamp:
                self._chop_timestamps[result.chop_name] = now
                timestamps_dirty = True
            if result.executed and result.duration_seconds is not None:
                self._chop_durations[result.chop_name] = result.duration_seconds
        if timestamps_dirty:
            write_chop_timestamps(
                self.name,
                {k: v.isoformat() for k, v in self._chop_timestamps.items()},
            )

        tick_duration = time.monotonic() - _tick_start
        if tick_duration > self.config.interval:
            capped = (
                f" ({len(eligible_chops)} jobs, max_concurrent_jobs={max_workers})"
                if len(eligible_chops) > max_workers
                else ""
            )
            self._log(
                f"Tick overrun: took {tick_duration:.1f}s but interval is "
                f"{self.config.interval}s{capped}",
                style="yellow",
            )

        self._metrics.cycles_run += 1
        self._record_tick_load(
            spawns=tick_spawns,
            skipped=tick_skipped,
            no_ops=tick_no_ops,
        )
        self._update_status()
        self._update_metrics()
        AXE_CYCLES.labels(cycle_type=self.name).inc()
        AXE_CYCLE_DURATION.labels(cycle_type=self.name).observe(tick_duration)
