"""Single-lumberjack scheduler loop.

A Lumberjack runs a subset of chops on a fixed interval using the
``schedule`` library.  The Orchestrator spawns one Lumberjack per
configured lumberjack definition (e.g. hooks, checks, comments,
housekeeping).
"""

import os
import signal
import time
import traceback
from collections.abc import Callable
from datetime import datetime

import schedule
from rich.console import Console

from sase.ace.query import QueryExpr, parse_query
from sase.sase_utils import EASTERN_TZ

from .check_cycles import CheckCycleRunner
from .chop_registry import ChopContext, get_chop
from .config import AxeConfig, LumberjackConfig
from .runner_pool import RunnerPool
from .state import (
    AxeMetrics,
    LumberjackMetrics,
    LumberjackStatus,
    append_error,
    ensure_lumberjack_dirs,
    get_timestamp,
    lumberjack_log_path,
    remove_lumberjack_pid,
    write_lumberjack_metrics,
    write_lumberjack_pid,
    write_lumberjack_status,
)

LogCallback = Callable[[str, str | None], None]


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
        self.runner_pool = RunnerPool(axe_config.max_runners)

        self._state_dir = ensure_lumberjack_dirs(name)
        self._log_file_path = lumberjack_log_path(name)
        self._start_time = datetime.now(EASTERN_TZ)
        self._running = True
        self._metrics = LumberjackMetrics()
        self._axe_metrics = AxeMetrics()
        self._check_runner = CheckCycleRunner(self.parsed_query, self._log)

    def _log(self, message: str, style: str | None = None) -> None:
        timestamp = datetime.now(EASTERN_TZ).strftime("%Y-%m-%d %H:%M:%S")
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
        """Execute one tick: refresh changespecs, build context, invoke chops."""
        all_changespecs = self._check_runner.get_all_changespecs()
        filtered_changespecs = self._check_runner.get_filtered_changespecs(
            all_changespecs
        )

        ctx = ChopContext(
            log_callback=self._log,
            runner_pool=self.runner_pool,
            metrics=self._axe_metrics,
            parsed_query=self.parsed_query,
            max_runners=self.axe_config.max_runners,
            zombie_timeout_seconds=self.axe_config.zombie_timeout_seconds,
            all_changespecs=all_changespecs,
            filtered_changespecs=filtered_changespecs,
            lumberjack_name=self.name,
            state_dir=self._state_dir,
        )

        for chop_name in self.config.chops:
            try:
                chop_func = get_chop(chop_name)
                chop_func(ctx)
                self._metrics.chops_executed += 1
            except Exception as e:
                self._handle_error(chop_name, e)

        self._metrics.cycles_run += 1

    def _handle_error(self, job_name: str, error: Exception) -> None:
        self._log(f"Error in {job_name}: {error}", style="red")
        self._metrics.errors_encountered += 1
        error_info = {
            "timestamp": get_timestamp(),
            "lumberjack": self.name,
            "job": job_name,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        append_error(error_info)

    def _update_status(self) -> None:
        now = datetime.now(EASTERN_TZ)
        uptime = int((now - self._start_time).total_seconds())
        status = LumberjackStatus(
            name=self.name,
            pid=os.getpid(),
            started_at=self._start_time.isoformat(),
            status="running",
            interval=self.config.interval,
            chops=self.config.chops,
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

        # Schedule the tick at the configured interval
        self.scheduler.every(self.config.interval).seconds.do(self._run_tick)

        # Status/metrics updates
        self.scheduler.every(5).seconds.do(self._update_status)
        self.scheduler.every(30).seconds.do(self._update_metrics)

        self._log(
            f"Lumberjack '{self.name}' started (PID: {os.getpid()}, "
            f"interval: {self.config.interval}s, "
            f"chops: {', '.join(self.config.chops)})"
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
