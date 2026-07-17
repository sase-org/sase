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

import schedule
from rich.console import Console

from sase.ace.hooks.processes import is_process_running
from sase.ace.query import parse_query
from sase.core.time import get_timezone
from sase.telemetry import init_telemetry
from sase.telemetry.metrics import AXE_CYCLE_DURATION, AXE_CYCLES, AXE_ERRORS

from .check_cycles import CheckCycleRunner
from .chop_agents import (
    build_chop_launch_env,
    get_live_chop_agent_records,
    prompt_hash,
)
from .chop_runner import (
    TRACEBACK_UNAVAILABLE as _TRACEBACK_UNAVAILABLE,
    ChopRunOutcome,
    run_configured_chop_once,
)
from .chop_script_context import (
    ChopScriptContext,
    serialize_changespecs,
    write_chop_context,
)
from .config import AxeConfig, ChopConfig, LumberjackConfig
from .maintenance import clear_stale_maintenance, read_maintenance
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
    agent_pid: int | None = None  # Set for successful agent chop launches


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
        self._metrics = LumberjackMetrics()
        self._axe_metrics = AxeMetrics()
        self._check_runner = CheckCycleRunner(axe_config.query or None, self._log)
        # Track running agent processes per chop (singleton per chop)
        self._agent_pids: dict[str, set[int]] = {}
        # Load persisted chop last-run timestamps for time-based run_every
        self._chop_timestamps: dict[str, datetime] = {}
        for chop_name, ts_str in read_chop_timestamps(name).items():
            try:
                self._chop_timestamps[chop_name] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                pass

    def _log(self, message: str, style: str | None = None) -> None:
        timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"[{timestamp}] [{self.name}] {message}"
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
        )

    def _run_tick(self) -> None:
        """Execute one tick: refresh changespecs, serialize context, invoke chop scripts."""
        _tick_start = time.monotonic()
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
            AXE_CYCLES.labels(cycle_type=self.name).inc()
            AXE_CYCLE_DURATION.labels(cycle_type=self.name).observe(tick_duration)
            return

        all_changespecs = self._check_runner.get_all_changespecs()
        filtered_changespecs = self._check_runner.get_filtered_changespecs(
            all_changespecs
        )

        # Serialize changespecs and context to disk for chop scripts
        tick_dir = self._state_dir / "tick"
        tick_dir.mkdir(parents=True, exist_ok=True)

        all_cs_file = str(tick_dir / "all_changespecs.json")
        filtered_cs_file = str(tick_dir / "filtered_changespecs.json")
        context_file = str(tick_dir / "context.json")

        serialize_changespecs(all_changespecs, all_cs_file)
        serialize_changespecs(filtered_changespecs, filtered_cs_file)

        ctx = ChopScriptContext(
            max_hook_runners=self.axe_config.max_hook_runners,
            max_agent_runners=self.axe_config.max_agent_runners,
            zombie_timeout_seconds=self.axe_config.zombie_timeout_seconds,
            query=self.axe_config.query,
            lumberjack_name=self.name,
            state_dir=str(self._state_dir),
            all_changespecs_file=all_cs_file,
            filtered_changespecs_file=filtered_cs_file,
            verbose_lumberjack_diagnostics=(
                self.axe_config.verbose_lumberjack_diagnostics
            ),
        )
        write_chop_context(ctx, context_file)

        now = datetime.now(get_timezone())

        # Filter eligible chops (run_every + agent dedup checks in main thread)
        eligible_script_chops: list[ChopConfig] = []
        eligible_agent_chops: list[ChopConfig] = []
        for chop in self.config.chops:
            if chop.run_every is not None:
                last_run = self._chop_timestamps.get(chop.name)
                if last_run is not None:
                    elapsed = (now - last_run).total_seconds()
                    if elapsed < chop.run_every:
                        continue
            if chop.agent is not None:
                if not self._is_agent_eligible(chop):
                    continue
                eligible_agent_chops.append(chop)
            else:
                eligible_script_chops.append(chop)

        # Run script chops concurrently. Agent launches are sequentialized below
        # because launch preparation allocates workspaces before the eventual
        # RUNNING-field claim, so same-tick launches can race on one workspace.
        results: list[_ChopResult] = []
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self._run_single_chop, chop, context_file): chop
                for chop in eligible_script_chops
            }
            for chop in eligible_agent_chops:
                results.append(self._run_single_chop(chop, context_file))
            for future in as_completed(futures):
                results.append(future.result())

        # Aggregate results in the main thread
        timestamps_dirty = False
        for result in results:
            for line in result.log_lines:
                self._log(line)
            if result.error is not None:
                self._handle_error(result.chop_name, result.error, result.traceback)
            if result.executed and result.success:
                self._metrics.chops_executed += 1
            if result.update_timestamp:
                self._chop_timestamps[result.chop_name] = now
                timestamps_dirty = True
            if result.agent_pid is not None:
                self._agent_pids.setdefault(result.chop_name, set()).add(
                    result.agent_pid
                )

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
        AXE_CYCLES.labels(cycle_type=self.name).inc()
        AXE_CYCLE_DURATION.labels(cycle_type=self.name).observe(tick_duration)

    def _run_single_chop(self, chop: ChopConfig, context_file: str) -> _ChopResult:
        """Execute a single chop via the shared chop-runner service.

        The runner owns context, env, timeout, and run-history persistence;
        this method translates the typed :class:`ChopRunOutcome` it returns
        into the tick-level :class:`_ChopResult` (log lines for the aggregate
        log, run_every timestamp updates, agent PID tracking).
        """
        outcome = run_configured_chop_once(
            lumberjack_name=self.name,
            chop=chop,
            axe_config=self.axe_config,
            chop_timeout_default=self.config.chop_timeout,
            context_file=context_file,
            source="scheduled",
        )
        return self._outcome_to_result(chop, outcome)

    def _outcome_to_result(
        self, chop: ChopConfig, outcome: ChopRunOutcome
    ) -> _ChopResult:
        log_lines: list[str] = []

        if outcome.status == "success":
            self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=True,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
            )

        if outcome.status == "failure" and outcome.exit_code is not None:
            # Process completed with nonzero exit; echo its tail into the
            # aggregate log to match the legacy ``capture_output=True`` shape.
            self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
            )

        if outcome.status == "failure":
            # Exception raised before/during streaming — no tail to echo.
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
            )

        if outcome.status == "timeout":
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
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

        if outcome.status == "agent_launched":
            launch_line = f"Launched agent chop '{chop.name}' (PID {outcome.agent_pid})"
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=True,
                update_timestamp=chop.run_every is not None,
                log_lines=[launch_line],
                agent_pid=outcome.agent_pid,
            )

        if outcome.status == "agent_failed":
            # Throttle persistent launch failures by the chop's normal
            # cadence so a misconfigured agent chop doesn't retry every
            # tick and flood error digests.
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=chop.run_every is not None,
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
            error=RuntimeError(f"unexpected chop run outcome: {outcome.status}"),
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

    def _is_agent_eligible(self, chop: ChopConfig) -> bool:
        """Check if an agent chop should run (no live instances).

        Must be called from the main thread only.
        """
        assert chop.agent is not None
        prompt_hash_value = prompt_hash(chop.agent)
        live_records = get_live_chop_agent_records(
            self.name,
            chop_name=chop.name,
            prompt_hash_value=prompt_hash_value,
        )
        if live_records:
            live_pids = {record.pid for record in live_records}
            self._agent_pids[chop.name] = live_pids
            self._log(
                f"Skipping agent chop '{chop.name}': already running (PIDs {live_pids})"
            )
            return False

        self._reap_agent_pids(chop.name)
        live_pids = self._agent_pids.get(chop.name, set())
        still_alive: set[int] = set()
        for pid in live_pids:
            if is_process_running(pid):
                still_alive.add(pid)
        if still_alive:
            self._agent_pids[chop.name] = still_alive
            self._log(
                f"Skipping agent chop '{chop.name}': already running (PIDs {still_alive})"
            )
            return False
        self._agent_pids.pop(chop.name, None)
        return True

    def _reap_agent_pids(self, chop_name: str) -> None:
        """Reap exited direct child agent PIDs tracked by this lumberjack."""
        pids = self._agent_pids.get(chop_name)
        if not pids:
            return

        remaining: set[int] = set()
        for pid in pids:
            try:
                reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                remaining.add(pid)
                continue
            if reaped_pid == 0:
                remaining.add(pid)

        if remaining:
            self._agent_pids[chop_name] = remaining
        else:
            self._agent_pids.pop(chop_name, None)

    def _chop_launch_env(self, chop: ChopConfig) -> dict[str, str]:
        """Build env vars that identify a chop-launched workflow."""
        return build_chop_launch_env(
            lumberjack_name=self.name,
            chop_name=chop.name,
            prompt=chop.agent,
        )

    def _launch_agent_chop(self, chop: ChopConfig) -> _ChopResult:
        """Launch an agent chop via the shared runner.

        Kept as a method so the existing test suite can call it directly;
        delegates to :func:`run_configured_chop_once` for the actual launch
        and history-writing work.
        """
        outcome = run_configured_chop_once(
            lumberjack_name=self.name,
            chop=chop,
            axe_config=self.axe_config,
            chop_timeout_default=self.config.chop_timeout,
            source="scheduled",
        )
        return self._outcome_to_result(chop, outcome)

    def _handle_error(
        self, job_name: str, error: Exception, tb: str | None = None
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
        error_info = {
            "timestamp": get_timestamp(),
            "lumberjack": self.name,
            "job": job_name,
            "error": str(error),
            "traceback": tb if tb is not None else _TRACEBACK_UNAVAILABLE,
        }
        append_error(error_info)

    def _update_status(self) -> None:
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
        )
        write_lumberjack_status(status)

    def _update_metrics(self) -> None:
        write_lumberjack_metrics(self.name, self._metrics)

    def _handle_shutdown(self, _signum: int, _frame: object) -> None:
        self._log("Received shutdown signal, stopping...")
        self._running = False

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

        # Schedule the tick at the configured interval
        self.scheduler.every(self.config.interval).seconds.do(self._run_tick)

        # Status/metrics updates
        self.scheduler.every(5).seconds.do(self._update_status)
        self.scheduler.every(30).seconds.do(self._update_metrics)

        self._log(
            f"Lumberjack '{self.name}' started (PID: {os.getpid()}, "
            f"interval: {self.config.interval}s, "
            f"chops: {', '.join(self.config.chop_names)})"
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
            self._log(f"Lumberjack '{self.name}' stopped")

        return True
