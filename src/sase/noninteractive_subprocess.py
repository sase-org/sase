"""Subprocess helpers for captured, non-interactive background commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import signal
import subprocess

DEFAULT_NONINTERACTIVE_TIMEOUT_SECONDS = 900.0
_TERMINATE_GRACE_SECONDS = 1.0


def run_noninteractive(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = DEFAULT_NONINTERACTIVE_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run a captured command that cannot read from the caller's terminal."""
    args = list(argv)
    process = _start_noninteractive_process(
        args,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        assert timeout is not None
        _terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            args,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(
        args,
        process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _start_noninteractive_process(
    args: Sequence[str],
    *,
    cwd: str | Path | None,
    env: Mapping[str, str] | None,
) -> subprocess.Popen[str]:
    """Start the captured subprocess with the production isolation contract."""
    return subprocess.Popen(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.terminate()
        except ProcessLookupError:
            return


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            return


__all__ = [
    "DEFAULT_NONINTERACTIVE_TIMEOUT_SECONDS",
    "run_noninteractive",
]
