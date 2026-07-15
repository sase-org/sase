"""Bounded git command execution for SDD operations."""

from collections.abc import Mapping
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

ENV_LOCAL_TIMEOUT = "SASE_SDD_GIT_LOCAL_TIMEOUT"
ENV_NETWORK_TIMEOUT = "SASE_SDD_GIT_NETWORK_TIMEOUT"
ENV_SLOW_MS = "SASE_SDD_GIT_SLOW_MS"

DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SLOW_GIT_MS = 1_000.0


class SddGitCommandTimeout(RuntimeError):
    """Raised when a bounded SDD git command exceeds its timeout."""


def run_sdd_git(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    timeout: float | None = None,
    check: bool,
    capture_output: bool,
    text: bool = False,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Run a bounded git command with SDD telemetry."""
    timeout_seconds = timeout if timeout is not None else _local_git_timeout()
    cmd = ["git", *args]
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            capture_output=capture_output,
            text=text,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="timeout",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=None,
            stdout=exc.stdout,
            stderr=exc.stderr,
        )
        raise SddGitCommandTimeout(
            f"git operation {op!r} timed out after {timeout_seconds:.1f}s in {cwd}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="error",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=exc.returncode,
            stdout=exc.stdout,
            stderr=exc.stderr,
        )
        raise

    duration_ms = (time.perf_counter() - start) * 1000.0
    if _should_log_git_operation(args, duration_ms, result.returncode):
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="ok" if result.returncode == 0 else "nonzero",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def network_git_timeout() -> float:
    """Return the configured timeout for SDD network git operations."""
    return _network_git_timeout()


def _should_log_git_operation(
    args: list[str],
    duration_ms: float,
    returncode: int,
) -> bool:
    if returncode != 0:
        return True
    if any(arg in {"push", "fetch"} for arg in args):
        return True
    return duration_ms >= _slow_git_ms()


def _log_git_operation(
    *,
    op: str,
    cmd: list[str],
    cwd: Path,
    status: str,
    duration_ms: float,
    timeout_seconds: float,
    returncode: int | None,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> None:
    try:
        from sase.logs import log_tui_git_operation

        log_tui_git_operation(
            {
                "ts": time.time(),
                "event": "sdd_git_operation",
                "operation": op,
                "status": status,
                "duration_ms": round(duration_ms, 3),
                "timeout_seconds": timeout_seconds,
                "returncode": returncode,
                "cwd": str(cwd),
                "cmd": cmd,
                "stdout_preview": _preview_stream(stdout),
                "stderr_preview": _preview_stream(stderr),
            }
        )
    except Exception:
        _logger.debug("failed to write SDD git operation telemetry", exc_info=True)


def _preview_stream(value: str | bytes | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    text = text.strip()
    if not text:
        return None
    return text[:limit]


def _local_git_timeout() -> float:
    return _float_env(ENV_LOCAL_TIMEOUT, DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS)


def _network_git_timeout() -> float:
    return _float_env(ENV_NETWORK_TIMEOUT, DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS)


def _slow_git_ms() -> float:
    return _float_env(ENV_SLOW_MS, DEFAULT_SLOW_GIT_MS)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default
