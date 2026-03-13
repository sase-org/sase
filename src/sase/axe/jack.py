"""Single-jack scheduler loop.

A Jack runs a subset of chops on a fixed interval using the
``schedule`` library.  The Orchestrator spawns one Jack per
configured jack definition (e.g. hooks, checks, comments,
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
from .chop_script_context import (
    ChopScriptContext,
    serialize_changespecs,
    write_chop_context,
)
from .chop_script_runner import discover_chop_script, run_chop_script
from .config import AxeConfig, ChopConfig, JackConfig
from .state import (
    AxeMetrics,
    JackMetrics,
    JackStatus,
    append_error,
    ensure_jack_dirs,
    get_timestamp,
    jack_log_path,
    remove_jack_pid,
    write_jack_metrics,
    write_jack_pid,
    write_jack_status,
)

LogCallback = Callable[[str, str | None], None]


class Jack:
    """Single-jack scheduler that runs a subset of chops.

    Each jack runs as a separate process, invoking its configured
    chops at a fixed interval.  Cross-process runner limits are
    coordinated via ``SharedRunnerPool``.
    """

    def __init__(
        self,
        name: str,
        config: JackConfig,
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

        self._state_dir = ensure_jack_dirs(name)
        self._log_file_path = jack_log_path(name)
        self._start_time = datetime.now(EASTERN_TZ)
        self._running = True
        self._metrics = JackMetrics()
        self._axe_metrics = AxeMetrics()
        self._check_runner = CheckCycleRunner(self.parsed_query, self._log)
        # Track running agent processes per chop (multiple allowed)
        self._agent_pids: dict[str, set[int]] = {}

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
        """Execute one tick: refresh changespecs, serialize context, invoke chop scripts."""
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
            jack_name=self.name,
            state_dir=str(self._state_dir),
            all_changespecs_file=all_cs_file,
            filtered_changespecs_file=filtered_cs_file,
        )
        write_chop_context(ctx, context_file)

        for chop in self.config.chops:
            if self._metrics.cycles_run % chop.run_every != 0:
                continue
            if chop.agent is not None:
                self._run_agent_chop(chop)
                continue
            try:
                script = discover_chop_script(
                    chop.name, self.axe_config.chop_script_dirs
                )
                if script is None:
                    self._handle_error(
                        chop.name,
                        RuntimeError(f"Chop script not found: {chop.name}"),
                    )
                    continue
                result = run_chop_script(script, context_file, env=chop.env)
                if result.stdout:
                    for line in result.stdout.strip().splitlines():
                        if line:
                            self._log(line)
                if result.returncode == 0:
                    self._metrics.chops_executed += 1
                else:
                    stderr = result.stderr.strip() if result.stderr else ""
                    self._handle_error(
                        chop.name,
                        RuntimeError(
                            f"exit code {result.returncode}"
                            + (f": {stderr}" if stderr else "")
                        ),
                    )
            except Exception as e:
                self._handle_error(chop.name, e)

        self._metrics.cycles_run += 1

    def _run_agent_chop(self, chop: ChopConfig) -> None:
        """Launch an agent chop as a background process."""
        assert chop.agent is not None

        # Clean up dead PIDs from previous launches
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
        else:
            self._agent_pids.pop(chop.name, None)

        try:
            from sase.agent_launcher import launch_agent_from_cwd

            result = launch_agent_from_cwd(chop.agent)
            self._agent_pids.setdefault(chop.name, set()).add(result.pid)
            self._log(f"Launched agent chop '{chop.name}' (PID {result.pid})")
            self._metrics.chops_executed += 1
        except Exception as e:
            self._handle_error(chop.name, e)

    def _handle_error(self, job_name: str, error: Exception) -> None:
        self._log(f"Error in {job_name}: {error}", style="red")
        self._metrics.errors_encountered += 1
        error_info = {
            "timestamp": get_timestamp(),
            "jack": self.name,
            "job": job_name,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        append_error(error_info)

    def _update_status(self) -> None:
        now = datetime.now(EASTERN_TZ)
        uptime = int((now - self._start_time).total_seconds())
        status = JackStatus(
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
        write_jack_status(status)

    def _update_metrics(self) -> None:
        write_jack_metrics(self.name, self._metrics)

    def _handle_shutdown(self, _signum: int, _frame: object) -> None:
        self._log("Received shutdown signal, stopping...")
        self._running = False

    def run(self) -> bool:
        """Run the jack main loop.

        Returns:
            True if exited normally.
        """
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        write_jack_pid(self.name)

        # Schedule the tick at the configured interval
        self.scheduler.every(self.config.interval).seconds.do(self._run_tick)

        # Status/metrics updates
        self.scheduler.every(5).seconds.do(self._update_status)
        self.scheduler.every(30).seconds.do(self._update_metrics)

        self._log(
            f"Jack '{self.name}' started (PID: {os.getpid()}, "
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
            remove_jack_pid(self.name)
            self._update_status()
            self._update_metrics()
            self._log(f"Jack '{self.name}' stopped")

        return True
