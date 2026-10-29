"""Process-group execution for the after-rebase gate hook."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from sase.core.rebase_gate import CommandFactsWire
from sase.workflows.commit._rebase_gate_common import (
    REBASE_GATE_CONTEXT_ENV,
    REBASE_GATE_RESULT_ENV,
    write_json_best_effort,
)
from sase.workflows.commit.hook_utils import (
    decode_tail,
    drain_stream,
)
from sase.workflows.commit.rebase_gate_budget import GateWorkBudget

_KILL_GRACE_SECONDS = 0.1
_INHERITED_PIPE_PROBE_SECONDS = 0.05


def run_gate_command(
    cmd: str,
    *,
    repo_root: str,
    context_path: Path,
    result_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    stdout_tail_path: Path,
    stderr_tail_path: Path,
    budget: GateWorkBudget,
    metadata: dict[str, object],
    metadata_path: Path,
) -> tuple[CommandFactsWire, str, str]:
    """Launch *cmd* within the remaining budget and always reap its group.

    Returns command facts plus the captured output tails. Cancellation
    terminates and reaps the subprocess group best-effort, then propagates.
    """
    remaining = budget.work_remaining
    if remaining <= 0:
        return {"timed_out": True}, "", ""
    command_started = budget.clock()
    deadline = time.monotonic() + remaining
    env = dict(os.environ)
    env[REBASE_GATE_CONTEXT_ENV] = str(context_path)
    env[REBASE_GATE_RESULT_ENV] = str(result_path)
    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            cwd=repo_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
    except OSError as exc:
        budget.charge_elapsed(command_started)
        metadata.update({"status": "failed_to_start", "error": str(exc)})
        write_json_best_effort(metadata_path, metadata)
        return (
            {"timed_out": False, "spawn_error": str(exc)},
            "",
            str(exc),
        )

    metadata.update({"status": "running", "pid": process.pid})
    write_json_best_effort(metadata_path, metadata)

    lock = threading.Lock()
    written = {"stdout": 0, "stderr": 0}
    truncated = {"stdout": False, "stderr": False}
    tails: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    threads = [
        threading.Thread(
            target=drain_stream,
            args=(
                process.stdout,
                "stdout",
                stdout_path,
                stdout_tail_path,
                lock,
                written,
                truncated,
                tails,
            ),
            daemon=True,
        ),
        threading.Thread(
            target=drain_stream,
            args=(
                process.stderr,
                "stderr",
                stderr_path,
                stderr_tail_path,
                lock,
                written,
                truncated,
                tails,
            ),
            daemon=True,
        ),
    ]
    timed_out = False
    term_signal: int | None = None
    teardown_deadline = deadline + budget.teardown_remaining
    try:
        for thread in threads:
            thread.start()
        exit_code, timed_out, term_signal = _wait_gate_process(
            process, deadline, budget
        )
        pipe_deadline = min(
            deadline,
            time.monotonic() + _INHERITED_PIPE_PROBE_SECONDS,
        )
        for thread in threads:
            thread.join(timeout=max(0.0, pipe_deadline - time.monotonic()))
        descendants = _process_group_exists(process.pid)
        readers_alive = any(thread.is_alive() for thread in threads)
        if not timed_out and (descendants or readers_alive):
            _terminate_and_reap_group(process, budget)
            timed_out = True
        _close_pipes(process)
        for thread in threads:
            thread.join(timeout=max(0.0, teardown_deadline - time.monotonic()))
    except BaseException:
        _terminate_and_reap_group(process, budget)
        _close_pipes(process)
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=min(0.05, budget.teardown_remaining))
        budget.charge_elapsed(command_started)
        raise
    budget.charge_elapsed(command_started)

    with lock:
        stdout_tail = decode_tail(tails["stdout"])
        stderr_tail = decode_tail(tails["stderr"])
        stdout_truncated = truncated["stdout"]
        stderr_truncated = truncated["stderr"]
    facts: CommandFactsWire = {"timed_out": timed_out}
    if term_signal is not None:
        facts["signal"] = term_signal
    else:
        facts["exit_code"] = exit_code
    metadata.update(
        {
            "status": "timeout" if timed_out else "finished",
            "returncode": exit_code,
            "signal": term_signal,
            "timed_out": timed_out,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
    )
    write_json_best_effort(metadata_path, metadata)
    return facts, stdout_tail, stderr_tail


def _wait_gate_process(
    process: subprocess.Popen[bytes],
    deadline: float,
    budget: GateWorkBudget,
) -> tuple[int | None, bool, int | None]:
    """Wait for *process* up to *deadline*; kill the group on timeout.

    Returns ``(exit_code, timed_out, signal)``. A returncode below zero is
    reported as a signal with no exit code.
    """
    remaining = deadline - time.monotonic()
    try:
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, remaining)
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        grace = min(_KILL_GRACE_SECONDS, budget.teardown_remaining / 2)
        _terminate_group(process)
        grace_end = time.monotonic() + grace
        _wait_group_until(process.pid, grace_end)
        _terminate_group(process, kill=True)
        try:
            returncode = process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            return None, True, None
        if returncode is None:
            return None, True, None
        return _split_returncode(returncode, timed_out=True)
    return _split_returncode(returncode, timed_out=False)


def _split_returncode(
    returncode: int, *, timed_out: bool
) -> tuple[int | None, bool, int | None]:
    if returncode < 0:
        return None, timed_out, -returncode
    return returncode, timed_out, None


def _terminate_group(process: subprocess.Popen[bytes], *, kill: bool = False) -> None:
    """Signal the subprocess group; never raises."""
    try:
        sig = signal.SIGKILL if kill else signal.SIGTERM
        os.killpg(process.pid, sig)
    except (OSError, AttributeError, ValueError):
        try:
            if kill:
                process.kill()
            else:
                process.terminate()
        except (OSError, ValueError):
            pass


def _process_group_exists(group_id: int) -> bool:
    """Return whether a hook process group still has any members."""
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, AttributeError, ValueError):
        return False
    return True


def _wait_group_until(group_id: int, deadline: float) -> None:
    """Give TERM-handling descendants a brief bounded chance to exit."""
    while time.monotonic() < deadline and _process_group_exists(group_id):
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def _terminate_and_reap_group(
    process: subprocess.Popen[bytes], budget: GateWorkBudget
) -> None:
    """Terminate descendants even when the original group leader exited."""
    grace = min(_KILL_GRACE_SECONDS, budget.teardown_remaining / 2)
    _terminate_group(process)
    _wait_group_until(process.pid, time.monotonic() + grace)
    _terminate_group(process, kill=True)
    try:
        process.wait(timeout=grace)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    """Close captured pipes so stray readers unblock; never raises."""
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass
