"""Child spawn, output-pump, wait, and settlement helpers for the executor."""

from __future__ import annotations

from collections.abc import Callable
import ctypes
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

# prctl(2) opcode for "deliver this signal when the parent dies". Loaded once
# at import so the pre-exec hook below never calls dlopen() after fork().
_PR_SET_PDEATHSIG = 1
_LIBC: ctypes.CDLL | None
try:
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
    _HAVE_PDEATHSIG = hasattr(_LIBC, "prctl")
except OSError:
    _LIBC = None
    _HAVE_PDEATHSIG = False


def _parent_death_preexec(parent_pid: int) -> None:
    """Arm SIGKILL-on-parent-death in a forked child, before exec.

    Best effort: platforms without prctl(2) (non-Linux, non-glibc) skip the
    arming and keep the separate session, so a SIGKILL of the caller's process
    group may orphan the child there. Linux glibc covers the common case.
    """

    if not _HAVE_PDEATHSIG or _LIBC is None:
        return
    try:
        _LIBC.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
    except Exception:  # noqa: BLE001 - pre-exec must never raise into Popen.
        return
    try:
        if os.getppid() != parent_pid:
            # The parent died between fork and arming; exit now so no orphan
            # outlives a wrapper that is already gone.
            os.kill(os.getpid(), signal.SIGKILL)
    except OSError:
        pass


def spawn_child(
    argv: tuple[str, ...],
    *,
    cwd: str | None,
    env: dict[str, str],
    start_new_session: bool,
    merged_streams: bool,
) -> subprocess.Popen[bytes]:
    """Spawn the tool child with an ownership-driven process group.

    The caller passes ``start_new_session=False`` under a live enclosing
    monitor/proc owner so the child joins the wrapper's own process group and
    the owner's ``killpg`` reaches the whole tree, and ``True`` for an inline
    run so the wrapper can signal the child tree without signaling itself or
    the caller's group. An inline child additionally arms a parent-death
    signal (Linux): no in-wrapper handler can catch a SIGKILL of the caller's
    group, so the kernel must deliver the child's death instead. The portable
    alternative — sharing the caller's process group — would make the
    wrapper's own TERM escalation SIGKILL the caller group including itself
    before it can settle the run, which is why the Linux-only prctl hook plus
    a bounded escalation was chosen; on platforms without prctl the inline
    child may orphan under a caller-group SIGKILL.
    """

    parent_pid = os.getpid()
    return subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merged_streams else subprocess.PIPE,
        start_new_session=start_new_session,
        preexec_fn=(
            (lambda: _parent_death_preexec(parent_pid)) if start_new_session else None
        ),
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


def _streams_share_target() -> bool:
    """Return whether fds 1 and 2 name the same device and inode."""

    try:
        first = os.fstat(1)
        second = os.fstat(2)
    except OSError:
        return False
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def should_merge_streams(*, owns_output: bool, compact: bool) -> bool:
    """Return whether the child gets one merged pipe instead of two.

    An enclosing owner holds the output (monitor logs, ``2>&1`` tails), so a
    single pipe preserves the child's write order; two pipes pumped on two
    threads regroup interleaved output by stream. Inline compact mode retains
    separate stdout/stderr logs and therefore keeps two pipes even when the
    wrapper's own fds share a target.
    """

    if compact:
        return False
    if not owns_output:
        return True
    return _streams_share_target()


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
    escalate: bool = True,
) -> int | None:
    """Wait for the child, escalating to SIGKILL unless owned.

    Under a live enclosing monitor/proc owner the wrapper skips its own
    ``TERM_ESCALATE_SECONDS`` SIGKILL escalation entirely (``escalate=False``):
    the owner's ``killpg`` reaches the whole tree because the child shares the
    wrapper's process group, and the owner stays the single process owner. An
    inline wrapper keeps the bounded escalation; it is the single owner there.
    """

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
            if not escalate:
                continue
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
    "should_merge_streams",
    "spawn_child",
    "spawn_diagnostic",
    "spawn_exit_code",
    "start_output_pumps",
    "wait_child",
]
