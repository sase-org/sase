"""Bounded git command execution for SDD operations."""

from collections.abc import Mapping
import logging
import os
import selectors
import subprocess
import time
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

ENV_LOCAL_TIMEOUT = "SASE_SDD_GIT_LOCAL_TIMEOUT"
ENV_NETWORK_TIMEOUT = "SASE_SDD_GIT_NETWORK_TIMEOUT"
ENV_NETWORK_TRANSFER_CEILING = "SASE_SDD_GIT_NETWORK_TRANSFER_CEILING"
ENV_SLOW_MS = "SASE_SDD_GIT_SLOW_MS"

DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS = 120.0
DEFAULT_NETWORK_GIT_TRANSFER_CEILING_SECONDS = 900.0
DEFAULT_SLOW_GIT_MS = 1_000.0
_DISABLE_RERERE_ARGS = (
    "-c",
    "rerere.enabled=false",
    "-c",
    "rerere.autoupdate=false",
)
_TRANSFER_COMMANDS = frozenset({"clone", "fetch", "push"})


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
    always_log: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run a bounded git command with SDD telemetry."""
    timeout_seconds = timeout if timeout is not None else _local_git_timeout()
    transfer_args = _transfer_args_with_progress(args) if capture_output else None
    if transfer_args is not None:
        return _run_streaming_sdd_git(
            transfer_args,
            cwd=cwd,
            op=op,
            stall_timeout_seconds=timeout_seconds,
            check=check,
            text=text,
            env=env,
            always_log=always_log,
        )

    cmd = sdd_git_command(args)
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
            timeout_reason="wall_clock",
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
    if always_log or _should_log_git_operation(args, duration_ms, result.returncode):
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


def sdd_git_command(args: list[str]) -> list[str]:
    """Return a git argv for machine-managed SDD repositories."""
    # SDD stores contain generated append-only JSONL. Their conflicts are
    # resolved semantically by SASE, so ambient rerere must not replay or
    # auto-stage a cached textual resolution over that semantic merge.
    return ["git", *_DISABLE_RERERE_ARGS, *args]


def network_git_timeout() -> float:
    """Return the configured timeout for SDD network git operations."""
    return _network_git_timeout()


def _run_streaming_sdd_git(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    stall_timeout_seconds: float,
    check: bool,
    text: bool,
    env: Mapping[str, str] | None,
    always_log: bool,
) -> subprocess.CompletedProcess[Any]:
    """Run a long git transfer, aborting on idle progress rather than wall time."""

    cmd = sdd_git_command(args)
    start = time.perf_counter()
    start_monotonic = time.monotonic()
    last_progress = start_monotonic
    ceiling_seconds = _network_transfer_ceiling_timeout()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        env=env,
    )
    with selectors.DefaultSelector() as selector:
        assert process.stdout is not None
        assert process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, stdout_chunks)
        selector.register(process.stderr, selectors.EVENT_READ, stderr_chunks)

        while selector.get_map():
            now = time.monotonic()
            stall_deadline = last_progress + stall_timeout_seconds
            ceiling_deadline = start_monotonic + ceiling_seconds
            next_deadline = min(stall_deadline, ceiling_deadline)
            if now >= next_deadline:
                if now >= ceiling_deadline:
                    reason = "ceiling"
                    message = (
                        f"git operation {op!r} exceeded streaming ceiling "
                        f"{_format_seconds(ceiling_seconds)}s in {cwd}"
                    )
                else:
                    reason = "stall"
                    message = (
                        f"git operation {op!r} stalled after "
                        f"{_format_seconds(stall_timeout_seconds)}s without "
                        f"progress in {cwd}"
                    )
                stdout, stderr = _terminate_streaming_git(
                    process,
                    stdout_chunks=stdout_chunks,
                    stderr_chunks=stderr_chunks,
                )
                duration_ms = (time.perf_counter() - start) * 1000.0
                _log_git_operation(
                    op=op,
                    cmd=cmd,
                    cwd=cwd,
                    status="timeout",
                    duration_ms=duration_ms,
                    timeout_seconds=stall_timeout_seconds,
                    returncode=process.returncode,
                    stdout=_decode_stream(stdout, text=text),
                    stderr=_decode_stream(stderr, text=text),
                    timeout_reason=reason,
                )
                raise SddGitCommandTimeout(message)

            events = selector.select(max(0.0, next_deadline - now))
            if not events:
                continue
            for key, _mask in events:
                file_obj = key.fileobj
                fd = file_obj if isinstance(file_obj, int) else file_obj.fileno()
                chunk = os.read(fd, 8192)
                if not chunk:
                    selector.unregister(file_obj)
                    continue
                key.data.append(chunk)
                if key.data is stderr_chunks:
                    last_progress = time.monotonic()

    returncode = process.wait()
    stdout_bytes = b"".join(stdout_chunks)
    stderr_bytes = b"".join(stderr_chunks)
    completed_stdout = _decode_stream(stdout_bytes, text=text)
    completed_stderr = _decode_stream(stderr_bytes, text=text)
    duration_ms = (time.perf_counter() - start) * 1000.0
    result: subprocess.CompletedProcess[Any] = subprocess.CompletedProcess(
        cmd,
        returncode,
        stdout=completed_stdout,
        stderr=completed_stderr,
    )
    if check and returncode != 0:
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="error",
            duration_ms=duration_ms,
            timeout_seconds=stall_timeout_seconds,
            returncode=returncode,
            stdout=completed_stdout,
            stderr=completed_stderr,
        )
        raise subprocess.CalledProcessError(
            returncode,
            cmd,
            output=completed_stdout,
            stderr=completed_stderr,
        )
    if always_log or _should_log_git_operation(args, duration_ms, returncode):
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="ok" if returncode == 0 else "nonzero",
            duration_ms=duration_ms,
            timeout_seconds=stall_timeout_seconds,
            returncode=returncode,
            stdout=completed_stdout,
            stderr=completed_stderr,
        )
    return result


def _terminate_streaming_git(
    process: subprocess.Popen[bytes],
    *,
    stdout_chunks: list[bytes],
    stderr_chunks: list[bytes],
) -> tuple[bytes, bytes]:
    process.kill()
    try:
        stdout, stderr = process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    if stdout:
        stdout_chunks.append(stdout)
    if stderr:
        stderr_chunks.append(stderr)
    return b"".join(stdout_chunks), b"".join(stderr_chunks)


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
    timeout_reason: str | None = None,
) -> None:
    try:
        from sase.logs import log_tui_git_operation

        record = {
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
        if timeout_reason is not None:
            record["timeout_reason"] = timeout_reason
        log_tui_git_operation(record)
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


def _network_transfer_ceiling_timeout() -> float:
    return _float_env(
        ENV_NETWORK_TRANSFER_CEILING,
        DEFAULT_NETWORK_GIT_TRANSFER_CEILING_SECONDS,
    )


def _slow_git_ms() -> float:
    return _float_env(ENV_SLOW_MS, DEFAULT_SLOW_GIT_MS)


def _transfer_args_with_progress(args: list[str]) -> list[str] | None:
    command_index = _git_subcommand_index(args)
    if command_index is None:
        return None
    command = args[command_index]
    if command not in _TRANSFER_COMMANDS:
        return None
    if "--quiet" in args or "-q" in args:
        return None
    progress_args = list(args)
    if "--progress" not in progress_args:
        progress_args.insert(command_index + 1, "--progress")
    return progress_args


def _git_subcommand_index(args: list[str]) -> int | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-c", "-C", "--git-dir", "--work-tree"}:
            index += 2
            continue
        if arg.startswith("-c") and arg != "-c":
            index += 1
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return index
    return None


def _decode_stream(value: bytes, *, text: bool) -> str | bytes:
    if text:
        return value.decode("utf-8", errors="replace")
    return value


def _format_seconds(value: float) -> str:
    return f"{value:.3g}"


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default
