"""Multi-lumberjack supervisor.

The Orchestrator spawns each configured lumberjack as a
``sase axe lumberjack run <name>`` subprocess, monitors them, and
restarts any that exit unexpectedly.  On SIGTERM the orchestrator
forwards the signal to all children and waits for them to exit.
"""

import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO

from sase.telemetry import init_telemetry
from sase.telemetry.metrics import (
    AXE_ERRORS,
    AXE_LUMBERJACK_RESTARTS,
    AXE_LUMBERJACKS_ACTIVE,
)

from .config import AxeConfig
from .lock import acquire_axe_lifetime_lock, read_lock_holder_pid
from .state import (
    AXE_STATE_DIR,
    append_bounded_log,
    reap_stale_log_rotation_temps,
)

# Orchestrator PID file (separate from per-lumberjack PIDs)
ORCHESTRATOR_PID_FILE = AXE_STATE_DIR / "orchestrator.pid"


class Orchestrator:
    """Multi-lumberjack supervisor that spawns and monitors children."""

    def __init__(self, config: AxeConfig) -> None:
        self.config = config
        self._children: dict[str, subprocess.Popen[bytes]] = {}
        self._log_threads: dict[str, threading.Thread] = {}
        self._running = True

    def _find_sase_executable(self) -> str:
        """Find the sase executable path.

        Uses the same Python executable's directory first, then falls
        back to ``shutil.which``.
        """
        # Try the bin directory of the current Python interpreter
        bin_dir = Path(sys.executable).parent
        sase_in_bin = bin_dir / "sase"
        if sase_in_bin.exists():
            return str(sase_in_bin)

        found = shutil.which("sase")
        if found:
            return found

        raise FileNotFoundError("Cannot find 'sase' executable")

    def _spawn_lumberjack(self, name: str) -> subprocess.Popen[bytes]:
        """Spawn a single lumberjack subprocess."""
        sase_cmd = self._find_sase_executable()
        cmd = [sase_cmd, "axe", "lumberjack", "run", name]

        # Forward relevant options
        if self.config.query:
            cmd.extend(["-q", self.config.query])
        cmd.extend(["--max-hook-runners", str(self.config.max_hook_runners)])
        cmd.extend(["--max-agent-runners", str(self.config.max_agent_runners)])
        cmd.extend(["--zombie-timeout", str(self.config.zombie_timeout_seconds)])

        # Ensure log directory exists
        log_dir = AXE_STATE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"lumberjack-{name}.log"

        append_bounded_log(
            log_file,
            f"[sase] orchestrator starting lumberjack '{name}'\n",
            max_bytes=self.config.lumberjack_log_max_bytes,
            temp_max_age_seconds=self.config.lumberjack_log_temp_max_age_seconds,
        )
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.stdout is not None:
            thread = threading.Thread(
                target=self._stream_child_output,
                args=(name, proc.stdout),
                daemon=True,
            )
            thread.start()
            self._log_threads[name] = thread
        return proc

    def _stream_child_output(self, name: str, stream: BinaryIO) -> None:
        log_file = AXE_STATE_DIR / "logs" / f"lumberjack-{name}.log"
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                append_bounded_log(
                    log_file,
                    chunk,
                    max_bytes=self.config.lumberjack_log_max_bytes,
                    temp_max_age_seconds=(
                        self.config.lumberjack_log_temp_max_age_seconds
                    ),
                )
        finally:
            stream.close()

    def _write_pid(self) -> None:
        AXE_STATE_DIR.mkdir(parents=True, exist_ok=True)
        ORCHESTRATOR_PID_FILE.write_text(str(os.getpid()))

    def _remove_pid(self, *, force: bool = False) -> None:
        pid = self._read_orchestrator_pid()
        if not force and pid is not None and pid != os.getpid():
            return
        try:
            ORCHESTRATOR_PID_FILE.unlink()
        except OSError:
            pass

    def _handle_shutdown(self, _signum: int, _frame: object) -> None:
        self._running = False
        self._terminate_children()

    def _read_orchestrator_pid(self) -> int | None:
        if not ORCHESTRATOR_PID_FILE.exists():
            return None

        try:
            return int(ORCHESTRATOR_PID_FILE.read_text().strip())
        except (ValueError, OSError):
            return None

    def _pid_is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _cleanup_stale_orchestrator_pid(self) -> int | None:
        """Remove stale PID files and return a live existing PID if present."""
        pid = self._read_orchestrator_pid()
        if pid is None:
            if ORCHESTRATOR_PID_FILE.exists():
                self._remove_pid(force=True)
            return None

        if pid == os.getpid() or self._pid_is_running(pid):
            return pid

        self._remove_pid(force=True)
        return None

    def run(self) -> bool:
        """Run the orchestrator main loop.

        Spawns all configured lumberjacks, monitors them, and restarts
        any that exit unexpectedly.

        Returns:
            True if exited normally.
        """
        lifecycle_lock = acquire_axe_lifetime_lock()
        if lifecycle_lock is None:
            existing_pid = self._read_orchestrator_pid() or read_lock_holder_pid()
            if existing_pid is not None:
                print(f"Axe orchestrator is already running (pid {existing_pid})")
            else:
                print("Axe orchestrator is already running")
            return True

        try:
            lifecycle_lock.write_holder_pid()
            existing_pid = self._cleanup_stale_orchestrator_pid()
            if existing_pid is not None and existing_pid != os.getpid():
                print(f"Axe orchestrator is already running (pid {existing_pid})")
                return True

            signal.signal(signal.SIGTERM, self._handle_shutdown)
            self._write_pid()
            reap_stale_log_rotation_temps(
                AXE_STATE_DIR,
                max_age_seconds=self.config.lumberjack_log_temp_max_age_seconds,
            )

            # Long-lived orchestrator metrics flush to the local store in batches.
            init_telemetry(start_flusher=True, source="orchestrator")

            # Spawn all lumberjacks
            for name in self.config.lumberjacks:
                try:
                    proc = self._spawn_lumberjack(name)
                    self._children[name] = proc
                except (FileNotFoundError, OSError) as e:
                    AXE_ERRORS.labels(error_type="spawn").inc()
                    print(f"Failed to spawn lumberjack '{name}': {e}", file=sys.stderr)

            try:
                while self._running:
                    # Update active lumberjack gauge
                    active = sum(1 for p in self._children.values() if p.poll() is None)
                    AXE_LUMBERJACKS_ACTIVE.set(active)

                    # Check children and restart any that exited unexpectedly
                    for name, proc in list(self._children.items()):
                        ret = proc.poll()
                        if ret is not None and self._running:
                            # Child exited unexpectedly — restart
                            print(
                                f"Lumberjack '{name}' exited (code {ret}), restarting...",
                                file=sys.stderr,
                            )
                            try:
                                new_proc = self._spawn_lumberjack(name)
                                self._children[name] = new_proc
                                AXE_LUMBERJACK_RESTARTS.inc()
                            except (FileNotFoundError, OSError) as e:
                                AXE_ERRORS.labels(error_type="spawn").inc()
                                print(
                                    f"Failed to restart lumberjack '{name}': {e}",
                                    file=sys.stderr,
                                )
                    time.sleep(1)
            except KeyboardInterrupt:
                self._running = False
                self._terminate_children()
            finally:
                # Wait for all children to exit (with escalation to SIGKILL)
                deadline = time.monotonic() + 10
                for _name, proc in self._children.items():
                    remaining = max(0, deadline - time.monotonic())
                    try:
                        proc.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                self._remove_pid()
        finally:
            lifecycle_lock.clear_holder_pid()
            lifecycle_lock.release()

        return True

    def _terminate_children(self) -> None:
        """Send SIGTERM to all live child processes."""
        for _name, proc in self._children.items():
            if proc.poll() is None:
                try:
                    os.kill(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
