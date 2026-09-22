"""Child spawn, output-pump, wait, and settlement helpers for the executor."""

from __future__ import annotations

from collections.abc import Callable
import errno
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import TYPE_CHECKING, BinaryIO

from sase.supervision.logs import pump_output
from sase.tool.executor_signals import SignalState

if TYPE_CHECKING:
    from sase.tool.argv import ResolvedToolArgv

TOOL_RUN_ID_ENV = "SASE_TOOL_RUN_ID"
TOOL_RUN_EVENTS_ENV = "SASE_TOOL_RUN_EVENTS"
TOOL_NAME_ENV = "SASE_TOOL_NAME"
TOOL_PROJECT_ROOT_ENV = "SASE_TOOL_PROJECT_ROOT"
TOOL_RUN_AGENT_ENV = "SASE_TOOL_RUN_AGENT"
TERM_ESCALATE_SECONDS = 5.0
KILL_WAIT_SECONDS = 2.0


def spawn_child(
    argv: tuple[str, ...],
    *,
    cwd: str | None,
    env: dict[str, str],
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def child_env(
    *,
    recorded: bool,
    run_id: str | None,
    events_path: Path | None,
    resolved: ResolvedToolArgv,
) -> dict[str, str]:
    env = os.environ.copy()
    if resolved.adhoc or not resolved.tool_name:
        env[TOOL_NAME_ENV] = "ad-hoc"
        env[TOOL_PROJECT_ROOT_ENV] = ""
    else:
        env[TOOL_NAME_ENV] = resolved.tool_name
        env[TOOL_PROJECT_ROOT_ENV] = resolved.cwd or ""
    if recorded and run_id:
        env[TOOL_RUN_ID_ENV] = run_id
        if events_path is not None:
            env[TOOL_RUN_EVENTS_ENV] = str(events_path)
        return env
    env.pop(TOOL_RUN_ID_ENV, None)
    env.pop(TOOL_RUN_EVENTS_ENV, None)
    return env


def start_output_pumps(
    proc: subprocess.Popen[bytes],
    on_stdout: Callable[[bytes], None],
    on_stderr: Callable[[bytes], None],
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    if proc.stdout is not None:
        thread = threading.Thread(
            target=_pump_child_stream,
            args=(proc.stdout, on_stdout),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    if proc.stderr is not None:
        thread = threading.Thread(
            target=_pump_child_stream,
            args=(proc.stderr, on_stderr),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    return threads


def _pump_child_stream(stream: BinaryIO, callback: Callable[[bytes], None]) -> None:
    # Signals must stay on the wrapper's main thread. A SIGTERM/SIGINT delivered
    # to a pump thread would take the default terminate action and skip finish().
    blocker = getattr(signal, "pthread_sigmask", None)
    if blocker is not None:
        blocker(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    pump_output(stream, callback)


def wait_child(
    proc: subprocess.Popen[bytes],
    signals: SignalState,
    *,
    on_tick: Callable[[], None] | None = None,
) -> int | None:
    escalate_at: float | None = None
    while True:
        try:
            return proc.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            if on_tick is not None:
                try:
                    on_tick()
                except Exception:  # noqa: BLE001 - ingest cannot change the child.
                    pass
            if (signals.sigint or signals.sigterm) and escalate_at is None:
                escalate_at = time.monotonic() + TERM_ESCALATE_SECONDS
            if escalate_at is not None and time.monotonic() >= escalate_at:
                if signals.pgid is not None:
                    try:
                        os.killpg(signals.pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                try:
                    return proc.wait(timeout=KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    return proc.poll()


def settle_wait_code(
    wait_code: int | None, signals: SignalState
) -> tuple[str, int, int | None, str | None]:
    if signals.sigint:
        return "interrupted", 130, signal.SIGINT, "wrapper SIGINT"
    if signals.sigterm:
        return "signaled", 143, signal.SIGTERM, "wrapper SIGTERM"
    if wait_code is None:
        return "failed", 1, None, None
    if wait_code < 0:
        sig = -wait_code
        return "signaled", 128 + sig, sig, None
    if wait_code == 0:
        return "succeeded", 0, None, None
    return "failed", wait_code, None, None


def spawn_exit_code(exc: OSError) -> int:
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return 127
    return 126


def spawn_diagnostic(exc: OSError, argv: tuple[str, ...]) -> str:
    program = argv[0] if argv else ""
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return f"executable not found: {program}"
    if exc.errno in {errno.EACCES, errno.EPERM, errno.EISDIR}:
        return f"not executable: {program}"
    return f"failed to launch {program}: {exc}"


__all__ = [
    "KILL_WAIT_SECONDS",
    "TERM_ESCALATE_SECONDS",
    "TOOL_NAME_ENV",
    "TOOL_PROJECT_ROOT_ENV",
    "TOOL_RUN_AGENT_ENV",
    "TOOL_RUN_EVENTS_ENV",
    "TOOL_RUN_ID_ENV",
    "child_env",
    "settle_wait_code",
    "spawn_child",
    "spawn_diagnostic",
    "spawn_exit_code",
    "start_output_pumps",
    "wait_child",
]
