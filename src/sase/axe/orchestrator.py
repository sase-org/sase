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
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
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
    append_error,
    get_timestamp,
    reap_stale_log_rotation_temps,
)

# Orchestrator PID file (separate from per-lumberjack PIDs)
ORCHESTRATOR_PID_FILE = AXE_STATE_DIR / "orchestrator.pid"

_RESTART_BACKOFF_INITIAL_SECONDS = 1.0
_RESTART_HEALTHY_RUN_SECONDS = 5 * 60.0
_CRASH_LOOP_WINDOW_SECONDS = 60.0
_CRASH_LOOP_FAILURE_THRESHOLD = 3
_CRASH_LOOP_TAIL_LINES = 20
_CRASH_LOOP_TAIL_MAX_BYTES = 8 * 1024


@dataclass
class _LumberjackRestartState:
    """Per-lumberjack restart history and pending retry state."""

    started_at: float | None = None
    restart_at: float | None = None
    backoff_seconds: float = 0.0
    consecutive_failures: int = 0
    recent_failures: deque[float] = field(default_factory=deque)
    last_exit_code: int | None = None
    alert_sent: bool = False


class Orchestrator:
    """Multi-lumberjack supervisor that spawns and monitors children."""

    def __init__(self, config: AxeConfig) -> None:
        self.config = config
        self._children: dict[str, subprocess.Popen[bytes]] = {}
        self._log_threads: dict[str, threading.Thread] = {}
        self._restart_states = {
            name: _LumberjackRestartState() for name in config.lumberjacks
        }
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
        # BufferedReader.read() waits for the requested byte count or EOF on a
        # pipe. read1() returns bytes already available from one raw read, so
        # quiet lumberjacks reach the aggregate log promptly.
        read_chunk = getattr(stream, "read1", stream.read)
        try:
            while True:
                chunk = read_chunk(64 * 1024)
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

    def _restart_state(self, name: str) -> _LumberjackRestartState:
        return self._restart_states.setdefault(name, _LumberjackRestartState())

    def _record_lumberjack_started(
        self,
        name: str,
        proc: subprocess.Popen[bytes],
        *,
        now: float,
    ) -> None:
        self._children[name] = proc
        state = self._restart_state(name)
        state.started_at = now
        state.restart_at = None
        state.last_exit_code = None

    def _schedule_lumberjack_restart(
        self,
        name: str,
        *,
        now: float,
        exit_code: int | None,
        spawn_error: OSError | None = None,
    ) -> float:
        """Record a failure and schedule the next bounded-backoff retry."""
        state = self._restart_state(name)
        healthy_run = (
            state.started_at is not None
            and now - state.started_at >= _RESTART_HEALTHY_RUN_SECONDS
        )
        if healthy_run:
            state.backoff_seconds = 0.0
            state.consecutive_failures = 0
            state.recent_failures.clear()
            state.alert_sent = False

        state.started_at = None
        state.consecutive_failures += 1
        if state.backoff_seconds == 0:
            state.backoff_seconds = _RESTART_BACKOFF_INITIAL_SECONDS
        else:
            state.backoff_seconds *= 2
        state.backoff_seconds = min(
            state.backoff_seconds,
            float(self.config.lumberjack_restart_backoff_max_seconds),
        )
        state.restart_at = now + state.backoff_seconds
        state.last_exit_code = exit_code

        cutoff = now - _CRASH_LOOP_WINDOW_SECONDS
        while state.recent_failures and state.recent_failures[0] < cutoff:
            state.recent_failures.popleft()
        state.recent_failures.append(now)

        if spawn_error is None:
            detail = f"exited (code {exit_code})"
        else:
            detail = f"failed to start ({spawn_error})"
        print(
            f"Lumberjack '{name}' {detail}; retrying in {state.backoff_seconds:g}s...",
            file=sys.stderr,
        )

        if (
            len(state.recent_failures) >= _CRASH_LOOP_FAILURE_THRESHOLD
            and not state.alert_sent
        ):
            state.alert_sent = True
            self._surface_crash_loop(
                name,
                exit_code=exit_code,
                failure_count=len(state.recent_failures),
                spawn_error=spawn_error,
            )

        return state.backoff_seconds

    def _surface_crash_loop(
        self,
        name: str,
        *,
        exit_code: int | None,
        failure_count: int,
        spawn_error: OSError | None,
    ) -> None:
        """Persist and notify one loud alert for a crash-loop episode."""
        thread = self._log_threads.get(name)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.2)

        log_file = AXE_STATE_DIR / "logs" / f"lumberjack-{name}.log"
        output_tail = self._read_recent_output_tail(log_file)
        if exit_code is not None:
            latest_failure = f"latest exit code {exit_code}"
        else:
            latest_failure = f"latest start failure: {spawn_error}"
        summary = (
            f"Lumberjack '{name}' is crash-looping: {failure_count} failures "
            f"within {int(_CRASH_LOOP_WINDOW_SECONDS)}s; {latest_failure}"
        )
        error_info = {
            "timestamp": get_timestamp(),
            "lumberjack": name,
            "job": "orchestrator_restart",
            "error": summary,
            "traceback": output_tail or "[no recent lumberjack output]",
        }
        try:
            append_error(error_info)
        except Exception as exc:
            print(
                f"Failed to record crash loop for lumberjack '{name}': {exc}",
                file=sys.stderr,
            )

        try:
            from sase.notifications.senders import notify_workflow_complete

            notify_workflow_complete(
                sender="axe",
                cl_name=None,
                success=False,
                notes=[
                    summary,
                    f"Recent output:\n{output_tail or '[no recent lumberjack output]'}",
                ],
                tags=["axe", "crash-loop"],
            )
        except Exception as exc:
            print(
                f"Failed to notify about crash loop for lumberjack '{name}': {exc}",
                file=sys.stderr,
            )

        AXE_ERRORS.labels(error_type="crash_loop").inc()

    @staticmethod
    def _read_recent_output_tail(log_file: Path) -> str:
        """Read a bounded output tail suitable for errors and notifications."""
        try:
            with log_file.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - _CRASH_LOOP_TAIL_MAX_BYTES))
                data = stream.read()
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-_CRASH_LOOP_TAIL_LINES:]).strip()

    def _poll_lumberjack(self, name: str, *, now: float) -> None:
        """Observe one lumberjack and perform its retry when due."""
        state = self._restart_state(name)
        proc = self._children.get(name)
        if proc is not None and state.restart_at is None:
            ret = proc.poll()
            if ret is None:
                return
            self._schedule_lumberjack_restart(
                name,
                now=now,
                exit_code=ret,
            )
            return

        if state.restart_at is None or now < state.restart_at:
            return

        try:
            new_proc = self._spawn_lumberjack(name)
        except (FileNotFoundError, OSError) as exc:
            AXE_ERRORS.labels(error_type="spawn").inc()
            self._schedule_lumberjack_restart(
                name,
                now=now,
                exit_code=None,
                spawn_error=exc,
            )
            return

        self._record_lumberjack_started(name, new_proc, now=now)
        AXE_LUMBERJACK_RESTARTS.inc()

    def _write_pid(self) -> None:
        AXE_STATE_DIR.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=ORCHESTRATOR_PID_FILE.parent,
                prefix=f".{ORCHESTRATOR_PID_FILE.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(f"{os.getpid()}\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, ORCHESTRATOR_PID_FILE)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

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
                    self._record_lumberjack_started(
                        name,
                        proc,
                        now=time.monotonic(),
                    )
                except (FileNotFoundError, OSError) as e:
                    AXE_ERRORS.labels(error_type="spawn").inc()
                    self._schedule_lumberjack_restart(
                        name,
                        now=time.monotonic(),
                        exit_code=None,
                        spawn_error=e,
                    )

            try:
                while self._running:
                    # Update active lumberjack gauge
                    active = sum(1 for p in self._children.values() if p.poll() is None)
                    AXE_LUMBERJACKS_ACTIVE.set(active)

                    # Check children and restart failures once their per-jack
                    # backoff deadline arrives. One crash loop cannot block
                    # monitoring of the other lumberjacks.
                    now = time.monotonic()
                    for name in self.config.lumberjacks:
                        if self._running:
                            self._poll_lumberjack(name, now=now)
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
