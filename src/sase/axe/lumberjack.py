"""Single-lumberjack scheduler loop.

A Lumberjack runs a subset of chops on a fixed interval using the
``schedule`` library.  The Orchestrator spawns one Lumberjack per
configured lumberjack definition (e.g. hooks, checks, comments,
housekeeping).
"""

import os
import signal
import subprocess
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import schedule
from rich.console import Console

from sase.ace.query import QueryExpr, parse_query
from sase.core.time import get_timezone
from sase.telemetry import init_telemetry, register_push_on_exit
from sase.telemetry.metrics import AXE_CYCLE_DURATION, AXE_CYCLES, AXE_ERRORS

from .check_cycles import CheckCycleRunner
from .chop_script_context import (
    ChopScriptContext,
    serialize_changespecs,
    write_chop_context,
)
from .chop_script_runner import discover_chop_script, run_chop_script
from .config import AxeConfig, ChopConfig, LumberjackConfig
from .state import (
    AxeMetrics,
    LumberjackMetrics,
    LumberjackStatus,
    append_error,
    ensure_lumberjack_dirs,
    get_timestamp,
    lumberjack_log_path,
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

        self.parsed_query: QueryExpr | None = None
        if axe_config.query:
            self.parsed_query = parse_query(axe_config.query)

        self.console = Console(record=True, force_terminal=True)
        self.scheduler = schedule.Scheduler()

        self._state_dir = ensure_lumberjack_dirs(name)
        self._log_file_path = lumberjack_log_path(name)
        self._start_time = datetime.now(get_timezone())
        self._running = True
        self._metrics = LumberjackMetrics()
        self._axe_metrics = AxeMetrics()
        self._check_runner = CheckCycleRunner(self.parsed_query, self._log)
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
        self._log_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_file_path, "a") as f:
            f.write(text)

    def _run_tick(self) -> None:
        """Execute one tick: refresh changespecs, serialize context, invoke chop scripts."""
        _tick_start = time.monotonic()
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
        )
        write_chop_context(ctx, context_file)

        now = datetime.now(get_timezone())

        # Filter eligible chops (run_every + agent dedup checks in main thread)
        eligible_chops: list[ChopConfig] = []
        for chop in self.config.chops:
            if chop.run_every is not None:
                last_run = self._chop_timestamps.get(chop.name)
                if last_run is not None:
                    elapsed = (now - last_run).total_seconds()
                    if elapsed < chop.run_every:
                        continue
            if chop.agent is not None and not self._is_agent_eligible(chop):
                continue
            eligible_chops.append(chop)

        # Run eligible chops concurrently
        results: list[_ChopResult] = []
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self._run_single_chop, chop, context_file): chop
                for chop in eligible_chops
            }
            for future in as_completed(futures):
                results.append(future.result())

        # Aggregate results in the main thread
        timestamps_dirty = False
        for result in results:
            for line in result.log_lines:
                self._log(line)
            if result.error is not None:
                self._handle_error(result.chop_name, result.error)
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
        """Execute a single chop (runs in a worker thread)."""
        if chop.agent is not None:
            return self._launch_agent_chop(chop)

        resolved_timeout = chop.timeout or self.config.chop_timeout
        log_lines: list[str] = []
        try:
            script = discover_chop_script(chop.name, self.axe_config.chop_script_dirs)
            if script is None:
                return _ChopResult(
                    chop_name=chop.name,
                    executed=False,
                    success=False,
                    update_timestamp=False,
                    error=RuntimeError(f"Chop script not found: {chop.name}"),
                )
            result = run_chop_script(
                script, context_file, timeout=resolved_timeout, env=chop.env
            )
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    if line:
                        log_lines.append(line)
            if result.returncode == 0:
                return _ChopResult(
                    chop_name=chop.name,
                    executed=True,
                    success=True,
                    update_timestamp=chop.run_every is not None,
                    log_lines=log_lines,
                )
            else:
                stderr = result.stderr.strip() if result.stderr else ""
                return _ChopResult(
                    chop_name=chop.name,
                    executed=True,
                    success=False,
                    update_timestamp=False,
                    log_lines=log_lines,
                    error=RuntimeError(
                        f"exit code {result.returncode}"
                        + (f": {stderr}" if stderr else "")
                    ),
                )
        except subprocess.TimeoutExpired:
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=RuntimeError(f"timed out after {resolved_timeout}s"),
            )
        except Exception as e:
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=e,
            )

    def _is_agent_eligible(self, chop: ChopConfig) -> bool:
        """Check if an agent chop should run (no live instances).

        Must be called from the main thread only.
        """
        live_pids = self._agent_pids.get(chop.name, set())
        still_alive: set[int] = set()
        for pid in live_pids:
            try:
                os.kill(pid, 0)
                still_alive.add(pid)
            except OSError:
                pass
        if still_alive:
            self._agent_pids[chop.name] = still_alive
            self._log(
                f"Skipping agent chop '{chop.name}': already running (PIDs {still_alive})"
            )
            return False
        self._agent_pids.pop(chop.name, None)
        return True

    def _launch_agent_chop(self, chop: ChopConfig) -> _ChopResult:
        """Launch an agent chop as a background process (runs in a worker thread)."""
        assert chop.agent is not None
        try:
            from sase.agent.launcher import launch_agent_from_cwd

            # Pass auto-dismiss via extra_env to avoid mutating os.environ
            # (not thread-safe). This ensures recurring run_every agents
            # don't accumulate as "done" entries.
            extra_env = (
                {"SASE_AGENT_AUTO_DISMISS": "1"} if chop.run_every is not None else None
            )
            result = launch_agent_from_cwd(chop.agent, extra_env=extra_env)
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=True,
                update_timestamp=chop.run_every is not None,
                log_lines=[f"Launched agent chop '{chop.name}' (PID {result.pid})"],
                agent_pid=result.pid,
            )
        except Exception as e:
            return _ChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=False,
                error=e,
            )

    def _handle_error(self, job_name: str, error: Exception) -> None:
        self._log(f"Error in {job_name}: {error}", style="red")
        self._metrics.errors_encountered += 1
        AXE_ERRORS.labels(error_type="chop").inc()
        error_info = {
            "timestamp": get_timestamp(),
            "lumberjack": self.name,
            "job": job_name,
            "error": str(error),
            "traceback": traceback.format_exc(),
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
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        write_lumberjack_pid(self.name)

        # Initialize telemetry and push metrics on exit
        init_telemetry()
        register_push_on_exit(job="lumberjack", lumberjack=self.name)

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
