"""Tailscale status command execution for built-in tailnet discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
import selectors
import shlex
import subprocess
import time
from typing import Any

from ._tailnet_common import (
    _TAILSCALE_STATUS_MAX_BYTES,
    _TAILSCALE_STDERR_MAX_BYTES,
    config_positive_float,
    config_positive_int,
    positive_timeout,
)


@dataclass(frozen=True)
class BoundedCommandResult:
    """Output from a subprocess that was supervised with hard caps."""

    stdout: bytes = b""
    stderr: bytes = b""
    returncode: int | None = None
    error_code: str = ""
    error_message: str = ""


def run_tailscale_status(
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> BoundedCommandResult:
    status_timeout = config_positive_float(
        config,
        "status_timeout_seconds",
        timeout_seconds,
    )
    max_bytes = config_positive_int(
        config,
        "status_max_bytes",
        _TAILSCALE_STATUS_MAX_BYTES,
    )
    return run_command_bounded(
        tailscale_status_argv(config),
        timeout_seconds=min(timeout_seconds, status_timeout),
        max_stdout_bytes=max_bytes,
    )


def run_command_bounded(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
) -> BoundedCommandResult:
    timeout = positive_timeout(timeout_seconds)
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv is explicit, no shell.
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except FileNotFoundError:
        return BoundedCommandResult(
            error_code="status_unavailable",
            error_message="tailscale CLI is not installed or not on PATH",
        )
    except OSError as exc:
        return BoundedCommandResult(
            error_code="status_unavailable",
            error_message=f"tailscale status could not start: {type(exc).__name__}",
        )

    selector = selectors.DefaultSelector()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_total = 0
    stderr_total = 0
    if proc.stdout is not None:
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    if proc.stderr is not None:
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process(proc)
                return BoundedCommandResult(
                    stdout=b"".join(stdout_chunks),
                    stderr=b"".join(stderr_chunks),
                    error_code="status_timeout",
                    error_message=f"tailscale status --json exceeded {timeout:g}s",
                )
            events = selector.select(remaining)
            if not events:
                continue
            for key, _mask in events:
                stream = key.fileobj
                fd = stream if isinstance(stream, int) else stream.fileno()
                chunk = os.read(fd, 65536)
                if not chunk:
                    selector.unregister(stream)
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                    continue
                if key.data == "stdout":
                    stdout_total += len(chunk)
                    if stdout_total > max_stdout_bytes:
                        _kill_process(proc)
                        return BoundedCommandResult(
                            stdout=b"".join(stdout_chunks),
                            stderr=b"".join(stderr_chunks),
                            error_code="status_output_too_large",
                            error_message=(
                                "tailscale status --json exceeded the output size "
                                f"limit of {max_stdout_bytes} bytes"
                            ),
                        )
                    stdout_chunks.append(chunk)
                else:
                    allowed = max(0, _TAILSCALE_STDERR_MAX_BYTES - stderr_total)
                    if allowed:
                        stderr_chunks.append(chunk[:allowed])
                    stderr_total += len(chunk)
        return BoundedCommandResult(
            stdout=b"".join(stdout_chunks),
            stderr=b"".join(stderr_chunks),
            returncode=proc.wait(timeout=0),
        )
    finally:
        selector.close()


def _kill_process(proc: subprocess.Popen[bytes]) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=1)
    except Exception:  # noqa: BLE001 - process is already being abandoned.
        pass


def tailscale_status_argv(config: Mapping[str, Any]) -> tuple[str, ...]:
    command = config.get("command", config.get("tailscale_command", "tailscale"))
    if isinstance(command, str):
        argv = tuple(shlex.split(command)) or ("tailscale",)
    elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
        argv = tuple(str(part) for part in command if str(part))
    else:
        argv = ("tailscale",)
    return (*argv, "status", "--json")
