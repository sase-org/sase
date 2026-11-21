"""Single-lumberjack scheduler loop.

A Lumberjack runs a subset of chops on a fixed interval using the
``schedule`` library.  The Orchestrator spawns one Lumberjack per
configured lumberjack definition (e.g. hooks, checks, comments,
housekeeping).
"""

import os
import signal
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import schedule
from rich.console import Console

from sase.ace.query import parse_query
from sase.core.code_swap_epoch import code_swap_writer_live, long_lived_swap_guard
from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.core.time import get_timezone
from sase.project_display_names import humanize_cl_names_in_text
from sase.telemetry import init_telemetry
from sase.telemetry.metrics import AXE_CYCLE_DURATION, AXE_CYCLES, AXE_ERRORS

from .check_cycles import CheckCycleRunner
from .chop_lifecycle import finalize_launched_chop_runs
from .chop_runner import (
    TRACEBACK_UNAVAILABLE as _TRACEBACK_UNAVAILABLE,
    ChopRunOutcome,
    run_configured_chop_once,
)
from .chop_stop_signal import ChopStopSignal
from .chop_script_context import ChopScriptContext
from .config import AxeConfig, ChopConfig, LumberjackConfig
from .maintenance import clear_stale_maintenance, read_maintenance
from .patch_filtering import filter_axe_candidate_patches
from .spawn_rate import spawn_rate_window_seconds
from .tick_context import TickContextWriter, routine_reads_tick_patches
from .state import (
    AxeMetrics,
    LumberjackMetrics,
    LumberjackStatus,
    append_lumberjack_log,
    append_error,
    ensure_lumberjack_dirs,
    get_timestamp,
    read_chop_run_log_tail,
    read_chop_timestamps,
    refresh_spawn_rate,
    remove_lumberjack_pid,
    write_chop_timestamps,
    write_lumberjack_metrics,
    write_lumberjack_pid,
    write_lumberjack_status,
)

LogCallback = Callable[[str, str | None], None]


@dataclass
class _ChopResult:
    """Result of running a single chop in a thread."""

    chop_name: str
    executed: bool  # True if the chop actually ran (not skipped)
    success: bool
    update_timestamp: bool  # Whether to update run_every timestamp
    log_lines: list[str] = field(default_factory=list)
    error: Exception | None = None
    # Captured ``traceback.format_exc()`` output. Must be recorded inside the
    # ``except`` block — by the time ``_handle_error`` runs we are no longer in
    # the active exception context, so a deferred ``format_exc()`` would
    # produce ``"NoneType: None"``.  When the chop failed without a Python
    # traceback (e.g. a subprocess exited nonzero), set this to a constant
    # placeholder rather than leaving it ``None``.
    traceback: str | None = None
    subprocess_diagnostic: dict[str, object] | None = None
    skip_reason: str | None = None
    no_op: bool = False


class Lumberjack:
    """Single-lumberjack scheduler that runs a subset of chops.

    Each lumberjack runs as a separate process, invoking its configured
    chops at a fixed interval.  Cross-process runner limits are
    coordinated via ``SharedRunnerPool``.
    """

    def __init__(
        self,
        name: str,
        config: LumberjackConfig,
        axe_config: AxeConfig,
    ) -> None:
        self.name = name
        self.config = config
        self.axe_config = axe_config

        # Parse upfront so a bad query fails the lumberjack at construction
        # time rather than mid-cycle. The check runner re-parses internally
        # via the batch facade, so we keep only the raw string here.
        if axe_config.query:
            parse_query(axe_config.query)

        self.console = Console(record=True, force_terminal=True)
        self.scheduler = schedule.Scheduler()

        self._state_dir = ensure_lumberjack_dirs(name)
        self._start_time = datetime.now(get_timezone())
        self._running = True
        # Set by run(): turns true once this routine outlived a code swap.
        self._swap_guard: Callable[[], bool] | None = None
        self._swap_hold_logged = False
        self.swap_restart_requested = False
        self._stop_signal = ChopStopSignal()
        self._metrics = LumberjackMetrics()
        self._axe_metrics = AxeMetrics()
        self._check_runner = CheckCycleRunner(axe_config.query or None, self._log)
        self._tick_context = TickContextWriter(
            self._state_dir / "tick",
            load_all_patches=lambda: filter_axe_candidate_patches(
                self._check_runner.get_all_patches()
            ),
            filter_patches=lambda patches: self._check_runner.get_filtered_patches(
                patches
            ),
        )
        # The first tick runs at start, so the observed span begins an interval
        # earlier (see sase.axe.spawn_rate).
        self._metrics.spawn_window_seconds = spawn_rate_window_seconds(config.interval)
        self._metrics.spawn_rate_since = time.time() - config.interval
        # Load persisted chop last-run timestamps for time-based run_every
        self._chop_timestamps: dict[str, datetime] = {}
        for chop_name, ts_str in read_chop_timestamps(name).items():
            try:
                self._chop_timestamps[chop_name] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                pass

    def _log(self, message: str, style: str | None = None) -> None:
        timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S")
        display_message = humanize_cl_names_in_text(message)
        full_message = f"[{timestamp}] [{self.name}] {display_message}"
        self.console.print(full_message, style=style, markup=False)
        self._flush_log_to_file()

    def _flush_log_to_file(self) -> None:
        text = self.console.export_text(styles=True, clear=True)
        if not text.strip():
            return
        append_lumberjack_log(
            self.name,
            text,
            max_bytes=self.axe_config.lumberjack_log_max_bytes,
            temp_max_age_seconds=(self.axe_config.lumberjack_log_temp_max_age_seconds),
        )

    def _held_for_code_swap(self) -> bool:
        """Whether this tick must start nothing because of a code swap.

        A routine that outlived a swap would mix pre-swap modules it already
        imported with post-swap modules it imports lazily from here on. While
        the writer is live, ticks are held. Once the swap completed, the
        routine stops so its supervisor restarts it on the new code.
        """
        guard = self._swap_guard
        if guard is None or not guard():
            self._swap_hold_logged = False
            return False
        if code_swap_writer_live():
            if not self._swap_hold_logged:
                self._swap_hold_logged = True
                self._log(
                    "A code swap is in progress; holding job starts until it finishes",
                    style="yellow",
                )
            return True
        self._log(
            "A code swap completed under this routine; restarting it on the new code"
        )
        self.swap_restart_requested = True
        self._running = False
        return True

    def _run_tick(self) -> None:
        """Execute one tick: refresh patches, serialize context, invoke chop scripts."""
        if self._held_for_code_swap():
            return
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

        # Script chops within one lumberjack tick run concurrently.
        # A shutdown request prevents any new worker from starting; the
        # current dispatch is allowed to acknowledge at its next boundary.
        results: list[_ChopResult] = []
        with ThreadPoolExecutor() as executor:
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
        if timestamps_dirty:
            write_chop_timestamps(
                self.name,
                {k: v.isoformat() for k, v in self._chop_timestamps.items()},
            )

        tick_duration = time.monotonic() - _tick_start
        if tick_duration > self.config.interval:
            self._log(
                f"Tick overrun: took {tick_duration:.1f}s but interval is {self.config.interval}s",
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

    def _build_chop_context(
        self, all_patches_file: str, filtered_patches_file: str
    ) -> ChopScriptContext:
        return ChopScriptContext(
            max_hook_runners=self.axe_config.max_hook_runners,
            max_agent_runners=self.axe_config.max_agent_runners,
            zombie_timeout_seconds=self.axe_config.zombie_timeout_seconds,
            query=self.axe_config.query,
            lumberjack_name=self.name,
            state_dir=str(self._state_dir),
            all_patches_file=all_patches_file,
            filtered_patches_file=filtered_patches_file,
            verbose_lumberjack_diagnostics=(
                self.axe_config.verbose_lumberjack_diagnostics
            ),
        )

    def _recover_pending_batches(self) -> list[Any]:
        """Reconcile pending launch batches before lifecycle cleanup or new work."""
        try:
            from sase.agent.launcher import (
                launch_agent_from_cwd,
                launch_agents_from_cwd,
            )

            from .chop_batch_recovery import recover_pending_chop_batches
        except Exception as exc:
            self._log(f"Unable to load chop batch recovery: {exc}", style="red")
            return []
        try:
            results = recover_pending_chop_batches(
                self.name,
                self.config.chop_names[0] if self.config.chop_names else "",
                launch_agents_from_cwd_fn=launch_agents_from_cwd,
                launch_agent_from_cwd_fn=launch_agent_from_cwd,
                pause_requested_fn=self._stop_signal.as_pause_fn(),
                jobs=list(self.config.chop_names),
            )
            return results
        except Exception as exc:
            self._log(f"Chop batch recovery failed: {exc}", style="red")
            return []

    def _run_single_chop(self, chop: ChopConfig, context_file: str) -> _ChopResult:
        """Execute a single chop via the shared chop-runner service.

        The runner owns context, env, timeout, and run-history persistence;
        this method translates the typed :class:`ChopRunOutcome` it returns
        into the tick-level :class:`_ChopResult` (log lines for the aggregate
        log, run_every timestamp updates, agent PID tracking).
        """
        if self._stop_signal.stop_requested() or not self._running:
            return _ChopResult(
                chop_name=chop.name,
                executed=False,
                success=True,
                update_timestamp=False,
                log_lines=[],
                skip_reason="shutdown",
            )
        outcome = run_configured_chop_once(
            lumberjack_name=self.name,
            chop=chop,
            axe_config=self.axe_config,
            chop_timeout_default=self.config.chop_timeout,
            wait_runners_default=self.config.wait_runners,
            context_file=context_file,
            source="scheduled",
            pause_requested_fn=self._stop_signal.as_pause_fn(),
        )
        return self._outcome_to_result(chop, outcome)

    def _outcome_to_result(
        self, chop: ChopConfig, outcome: ChopRunOutcome
    ) -> _ChopResult:
        log_lines: list[str] = []

        if outcome.status in {"success", "no_op", "launched", "action_succeeded"}:
            self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=True,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
                no_op=outcome.status == "no_op",
            )

        if outcome.status == "skipped":
            # A coalesced repeat skip already logged its line on the first skip.
            if not outcome.skip_coalesced:
                self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return _ChopResult(
                chop_name=chop.name,
                executed=False,
                success=True,
                update_timestamp=(
                    chop.run_every is not None and outcome.advances_cadence
                ),
                log_lines=log_lines,
                skip_reason=outcome.skip_reason or "inhibited",
            )

        if outcome.status in {"failure", "check_error", "action_failed"}:
            # Process completed with nonzero exit; echo its tail into the
            # aggregate log to match the legacy ``capture_output=True`` shape.
            self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
                subprocess_diagnostic=outcome.subprocess_diagnostic,
            )

        if outcome.status == "timeout":
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
                subprocess_diagnostic=outcome.subprocess_diagnostic,
            )

        if outcome.status == "missing_script":
            return _ChopResult(
                chop_name=chop.name,
                executed=False,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
            )

        if outcome.status == "already_running":
            # Scheduled tick should not double-launch; treat as a quiet skip
            # so we don't increment chops_executed or error counters.
            return _ChopResult(
                chop_name=chop.name,
                executed=False,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
            )

        # Unknown status: surface as an error so silent drift is loud.
        return _ChopResult(
            chop_name=chop.name,
            executed=False,
            success=False,
            update_timestamp=False,
            log_lines=log_lines,
            error=RuntimeError(f"unexpected job run outcome: {outcome.status}"),
            traceback=_TRACEBACK_UNAVAILABLE,
        )

    def _append_log_tail(
        self,
        chop_name: str,
        run_id: str | None,
        log_lines: list[str],
    ) -> None:
        if run_id is None:
            return
        try:
            tail = read_chop_run_log_tail(self.name, chop_name, run_id, lines=200)
        except OSError:
            tail = ""
        if tail:
            for line in tail.splitlines():
                if line:
                    log_lines.append(line)

    def _handle_error(
        self,
        job_name: str,
        error: Exception,
        tb: str | None = None,
        subprocess_diagnostic: dict[str, object] | None = None,
    ) -> None:
        self._log(f"Error in {job_name}: {error}", style="red")
        self._metrics.errors_encountered += 1
        AXE_ERRORS.labels(error_type="chop").inc()
        # Never call ``traceback.format_exc()`` here as a fallback: by the
        # time ``_handle_error`` runs we're outside the active ``except``
        # block, so it would yield the literal string ``"NoneType: None"``.
        # Every error-bearing ``_ChopResult`` is responsible for capturing
        # its own traceback inside the ``except`` block (or setting an
        # explicit placeholder for non-exception failures).
        error_info: dict[str, object] = {
            "timestamp": get_timestamp(),
            "lumberjack": self.name,
            "job": job_name,
            "error": str(error),
            "traceback": tb if tb is not None else _TRACEBACK_UNAVAILABLE,
        }
        if subprocess_diagnostic is not None:
            error_info["subprocess_diagnostic"] = subprocess_diagnostic
        append_error(error_info)

    def _update_status(self) -> None:
        refresh_spawn_rate(self._metrics)
        now = datetime.now(get_timezone())
        uptime = int((now - self._start_time).total_seconds())
        status = LumberjackStatus(
            name=self.name,
            pid=os.getpid(),
            started_at=self._start_time.isoformat(),
            status="running",
            interval=self.config.interval,
            chops=self.config.chop_names,
            last_cycle=now.isoformat(),
            cycles_run=self._metrics.cycles_run,
            errors_encountered=self._metrics.errors_encountered,
            uptime_seconds=uptime,
            last_tick_spawns=self._metrics.last_tick_spawns,
            last_tick_skipped=self._metrics.last_tick_skipped,
            last_tick_no_ops=self._metrics.last_tick_no_ops,
            spawn_rate_per_minute=self._metrics.spawn_rate_per_minute,
            no_op_ratio=self._metrics.no_op_ratio,
        )
        write_lumberjack_status(status)

    def _record_tick_load(
        self,
        *,
        spawns: int,
        skipped: int,
        no_ops: int,
        now: float | None = None,
    ) -> None:
        """Update last-tick counters and the rolling-window spawn rate."""
        current = time.time() if now is None else now
        if spawns > 0:
            self._metrics.spawn_samples.append([current, spawns])
        refresh_spawn_rate(self._metrics, now=current)
        self._metrics.last_tick_spawns = spawns
        self._metrics.last_tick_skipped = skipped
        self._metrics.last_tick_no_ops = no_ops
        self._metrics.last_tick_at = get_timestamp()
        spawned = self._metrics.chops_spawned
        self._metrics.no_op_ratio = (
            self._metrics.chops_no_op / spawned if spawned else 0.0
        )

    def _update_metrics(self) -> None:
        refresh_spawn_rate(self._metrics)
        write_lumberjack_metrics(self.name, self._metrics)

    def _handle_shutdown(self, _signum: int, _frame: object) -> None:
        # Signal handlers set state only; workers perform journaling and
        # notification work at safe boundaries.
        self._log("Received shutdown signal, stopping...")
        self._running = False
        try:
            self._stop_signal.request_stop()
        except Exception:
            pass

    def run(self) -> bool:
        """Run the lumberjack main loop.

        Returns:
            True if exited normally.
        """
        # The daemon can be started from a workspace directory that gets wiped
        # later in its lifetime, leaving a dangling kernel CWD pointer. Anchor
        # to $HOME up front so nothing in the daemon (logging, timestamps,
        # config loads) trips on os.getcwd() afterwards.
        os.chdir(os.path.expanduser("~"))

        signal.signal(signal.SIGTERM, self._handle_shutdown)
        write_lumberjack_pid(self.name)

        # Lumberjacks are long-lived, so flush their local deltas periodically.
        init_telemetry(start_flusher=True, source=f"lumberjack:{self.name}")
        self._swap_guard = long_lived_swap_guard()

        # Schedule the tick at the configured interval
        self.scheduler.every(self.config.interval).seconds.do(self._run_tick)

        # Status/metrics updates
        self.scheduler.every(5).seconds.do(self._update_status)
        self.scheduler.every(30).seconds.do(self._update_metrics)

        self._log(
            f"Routine '{self.name}' started (PID: {os.getpid()}, "
            f"interval: {self.config.interval}s, "
            f"jobs: {', '.join(self.config.chop_names)})"
        )

        # Write initial status
        self._update_status()

        # Run first tick immediately
        self._run_tick()

        try:
            while self._running:
                self.scheduler.run_pending()
                time.sleep(0.1)
        except KeyboardInterrupt:
            self._log("Shutting down...")
        finally:
            remove_lumberjack_pid(self.name)
            self._update_status()
            self._update_metrics()
            self._log(f"Routine '{self.name}' stopped")

        return True
