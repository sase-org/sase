"""Lumberjack core lifecycle: init, logging, status, and the run loop."""

import os
import signal
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import schedule
from rich.console import Console

from sase.ace.query import parse_query
from sase.core.code_swap_epoch import code_swap_writer_live, long_lived_swap_guard
from sase.core.time import get_timezone
from sase.project_display_names import humanize_cl_names_in_text
from sase.telemetry import init_telemetry
from sase.telemetry.metrics import AXE_CYCLE_DURATION, AXE_CYCLES

from .check_cycles import CheckCycleRunner
from .chop_script_context import ChopScriptContext
from .chop_stop_signal import ChopStopSignal
from .config import AxeConfig, ChopConfig, LumberjackConfig
from .patch_filtering import filter_axe_candidate_patches
from .routine_cadence import first_tick_delay, persists_cadence, read_last_tick_at
from .spawn_rate import spawn_rate_window_seconds
from .state import (
    AxeMetrics,
    LumberjackMetrics,
    LumberjackStatus,
    append_lumberjack_log,
    ensure_lumberjack_dirs,
    get_timestamp,
    read_chop_timestamps,
    refresh_spawn_rate,
    remove_lumberjack_pid,
    write_chop_timestamps,
    write_lumberjack_metrics,
    write_lumberjack_pid,
    write_lumberjack_status,
)
from .tick_context import TickContextWriter
from .tick_dispatch import dispatch_order, seed_durations
from ._lumberjack_chop import LumberjackChopMixin
from ._lumberjack_shared import LumberjackBase
from ._lumberjack_tick import LumberjackTickMixin


def _schedule_clock_after(seconds: float) -> datetime:
    """Return ``schedule``'s naive process-local clock ``seconds`` from now.

    ``schedule`` compares ``Job.next_run`` against bare ``datetime.now()``, so a
    deferred first tick must use that same clock; the value is never displayed.
    """
    return datetime.now() + timedelta(seconds=seconds)


class _LumberjackCoreMixin(LumberjackBase):
    """Construction, logging, cadence, status, and shutdown."""

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
        # Last observed wall seconds per chop, for longest-first dispatch.
        # Seeded from run history the first time a tick exceeds the cap.
        self._chop_durations: dict[str, float] = {}
        self._chop_durations_seeded = False
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

    def _dispatch_order(self, chops: list[ChopConfig]) -> list[ChopConfig]:
        """Order *chops* longest last-observed wall time first."""
        if not self._chop_durations_seeded:
            self._chop_durations_seeded = True
            seeded = seed_durations(self.name, self.config.chop_names)
            seeded.update(self._chop_durations)
            self._chop_durations = seeded
        return dispatch_order(chops, self._chop_durations)

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

    def _recover_pending_batches(self) -> list[object]:
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
            return list(results)
        except Exception as exc:
            self._log(f"Chop batch recovery failed: {exc}", style="red")
            return []

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

    def _first_tick_delay(self) -> float:
        """Seconds until this routine's first tick is due after a restart."""
        if not persists_cadence(self.config.interval):
            return 0.0
        return first_tick_delay(
            interval=self.config.interval,
            last_tick_at=read_last_tick_at(self.name),
            now=time.time(),
        )

    def _handle_shutdown(self, _signum: int, _frame: object) -> None:
        # Signal handlers set state only; workers perform journaling and
        # notification work at safe boundaries.
        self._log("Received shutdown signal, stopping...")
        self._running = False
        try:
            self._stop_signal.request_stop()
        except Exception:
            pass

    def run(self, *, tick_now: bool = False) -> bool:
        """Run the lumberjack main loop.

        Args:
            tick_now: Run the first tick at once even when the persisted
                cadence says the routine's next tick is not due yet.

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
        tick_job = self.scheduler.every(self.config.interval).seconds.do(self._run_tick)

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

        # Run the first tick now, unless a long-interval routine's persisted
        # cadence says it is not due yet (no restart burst).
        delay = 0.0 if tick_now else self._first_tick_delay()
        if delay > 0:
            tick_job.next_run = _schedule_clock_after(delay)
            self._log(
                f"Resuming the persisted cadence: next tick in {delay:.0f}s "
                "(run with --tick-now to tick at once)"
            )
        else:
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


class Lumberjack(_LumberjackCoreMixin, LumberjackTickMixin, LumberjackChopMixin):
    """Single-lumberjack scheduler that runs a subset of chops.

    Each lumberjack runs as a separate process, invoking its configured
    chops at a fixed interval.  Cross-process runner limits are
    coordinated via ``SharedRunnerPool``.  One tick runs at most
    ``config.max_concurrent_jobs`` chops at once, and a routine whose interval
    is at least a minute resumes its persisted cadence after a restart (see
    :mod:`sase.axe.routine_cadence`).
    """
