"""Antigravity (`agy`) subscription usage collector (a zero-token /usage probe)."""

from __future__ import annotations

import json
import os
import re
import select
import signal
import subprocess
import time
from typing import Any

from sase.core.rust import require_rust_binding
from sase.llm_provider.usage.types import (
    UsageCollectionOutcome,
    UsageProbeContext,
    UsageReasonCode,
    validated_status_observation,
)

_AGY_CLI_NAME = "agy"
_AGY_VERSION_FLOOR = (1, 1, 11)
_AGY_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_VERSION_PROBE_TIMEOUT_SECONDS = 2.0
# The worker's already-filtered ``os.environ`` is the base (H6): only add the
# flag that stops `agy` swapping its own binary mid-probe (H4).
_AGY_NO_AUTO_UPDATE_ENV = "AGY_CLI_DISABLE_AUTO_UPDATE"
# Logged-out print mode prints this to stderr and then blocks on an OAuth
# paste prompt that `--print-timeout` does not bound (H2).
_AUTH_PROMPT_MARKER = "authentication required"
_USAGE_ARGV = (
    "-p",
    "/usage",
    "--output-format",
    "json",
    "--mode",
    "plan",
    "--sandbox",
    "--print-timeout",
    "15s",
)
_LOG_FILE_NAME = "agy-usage.log"
_STDERR_MAX_BYTES = 65_536
_POLL_INTERVAL_SECONDS = 0.05
_KILL_GRACE_SECONDS = 0.2
_SUBPROCESS_CLEANUP_MARGIN_SECONDS = 0.25
_MIN_SUBPROCESS_DEADLINE_SECONDS = 0.1


def collect_agy_usage(
    context: UsageProbeContext, executable: str | None = None
) -> dict[str, Any]:
    """Collect Antigravity's subscription usage windows without a model turn."""
    command = executable or context.executable or _AGY_CLI_NAME
    version_status = _check_cli_version(command, context)
    if version_status is not None:
        return version_status
    # ``cwd=None`` inherits the probe worker's managed temp dir, which keeps
    # the log file out of ``~/.gemini/…`` (H5).
    workdir = context.working_directory or os.getcwd()
    _precreate_private_log(workdir)
    env = {**os.environ, _AGY_NO_AUTO_UPDATE_ENV: "1"}
    try:
        process = subprocess.Popen(
            [
                command,
                *_USAGE_ARGV,
                "--log-file",
                os.path.join(workdir, _LOG_FILE_NAME),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=context.working_directory,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        return _status(
            context,
            outcome="error",
            reason_code="not_installed",
            diagnostic="agy_executable_not_found",
        )
    except OSError:
        return _status(
            context,
            outcome="error",
            reason_code="probe_failed",
            diagnostic="agy_usage_spawn_failed",
        )
    stdout, saw_auth_prompt = _wait_for_usage(process, _subprocess_deadline(context))
    if stdout is None:
        if saw_auth_prompt:
            return _status(
                context,
                outcome="unauthenticated",
                reason_code="logged_out",
                diagnostic="agy_auth_prompt_detected",
            )
        return _status(
            context,
            outcome="error",
            reason_code="timeout",
            diagnostic="agy_usage_probe_timeout",
        )
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _status(
            context,
            outcome="error",
            reason_code="parse_error",
            diagnostic="agy_usage_stdout_not_json",
        )
    return _observation_from_payload(payload, context)


def _check_cli_version(
    command: str, context: UsageProbeContext
) -> dict[str, Any] | None:
    """Gate ``/usage`` behind the probe-safe CLI floor (H1).

    Older builds would run ``/usage`` as a real paid agent turn every tick,
    so anything below the floor — or anything unparseable — never spawns it.
    """
    remaining = context.deadline_at - time.time()
    if remaining <= 0:
        return _status(
            context,
            outcome="error",
            reason_code="deadline_exceeded",
            diagnostic="agy_version_probe_deadline_exceeded",
        )
    timeout = max(0.1, min(_VERSION_PROBE_TIMEOUT_SECONDS, remaining))
    try:
        completed = subprocess.run(
            [command, "--version"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _status(
            context,
            outcome="error",
            reason_code="not_installed",
            diagnostic="agy_executable_not_found",
        )
    except subprocess.TimeoutExpired:
        return _status(
            context,
            outcome="error",
            reason_code="timeout",
            diagnostic="agy_version_probe_timeout",
        )
    except OSError:
        return _status(
            context,
            outcome="error",
            reason_code="probe_failed",
            diagnostic="agy_version_probe_failed",
        )
    if completed.returncode != 0:
        return _unsupported(context, "agy_version_probe_failed")
    version = _parse_version(completed.stdout or completed.stderr)
    if version is None or version < _AGY_VERSION_FLOOR:
        return _unsupported(context, "agy_unsupported_cli_version")
    return None


def _unsupported(context: UsageProbeContext, diagnostic: str) -> dict[str, Any]:
    return _status(
        context,
        outcome="unsupported",
        reason_code="unsupported_cli_version",
        diagnostic=diagnostic,
    )


def _parse_version(output: str) -> tuple[int, int, int] | None:
    """Parse the first ``X.Y.Z`` triple; `agy --version` prints a bare one."""
    match = _AGY_VERSION_RE.search(output)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _precreate_private_log(workdir: str) -> None:
    """Pre-create the probe log file readable only by its owner."""
    path = os.path.join(workdir, _LOG_FILE_NAME)
    try:
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    except OSError:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _wait_for_usage(
    process: subprocess.Popen[bytes], deadline_at: float
) -> tuple[bytes | None, bool]:
    """Drain stdout/stderr until exit, the auth marker, or the deadline.

    Returns ``(stdout, saw_auth_prompt)``. ``stdout`` is set only when the
    child exited on its own; otherwise the whole process group is killed and
    the child reaped before returning.
    """
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    streams: dict[Any, str] = {}
    if process.stdout is not None:
        streams[process.stdout] = "stdout"
    if process.stderr is not None:
        streams[process.stderr] = "stderr"
    saw_auth_prompt = False
    while streams or process.poll() is None:
        remaining = deadline_at - time.time()
        if remaining <= 0:
            break
        if _AUTH_PROMPT_MARKER in _decode(stderr_buf).lower():
            saw_auth_prompt = True
            break
        ready, _, _ = select.select(
            list(streams), [], [], min(remaining, _POLL_INTERVAL_SECONDS)
        )
        for stream in ready:
            # ``os.read`` returns whatever is ready; a buffered ``read(n)``
            # would block until ``n`` bytes or EOF and hide the auth marker.
            try:
                chunk = os.read(stream.fileno(), 4096)
            except OSError:
                chunk = b""
            if not chunk:
                streams.pop(stream, None)
                continue
            if streams.get(stream) == "stdout":
                stdout_buf.extend(chunk)
            else:
                room = _STDERR_MAX_BYTES - len(stderr_buf)
                stderr_buf.extend(chunk[:room] if room > 0 else b"")
    exit_code = process.poll()
    _kill_process_group(process)
    if saw_auth_prompt or _AUTH_PROMPT_MARKER in _decode(stderr_buf).lower():
        return None, True
    if exit_code is not None:
        return bytes(stdout_buf), False
    return None, False


def _decode(data: bytes | bytearray) -> str:
    return bytes(data).decode("utf-8", errors="replace")


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM then SIGKILL the child's process group and reap it."""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        else:
            grace_until = time.time() + _KILL_GRACE_SECONDS
            while process.poll() is None and time.time() < grace_until:
                time.sleep(0.02)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass
    except OSError:
        pass
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _observation_from_payload(
    payload: Any, context: UsageProbeContext
) -> dict[str, Any]:
    from sase.llm_provider.agy import AgyProvider

    binding = require_rust_binding("provider_usage_normalize_agy_usage")
    observation = binding(
        {
            "schema_version": 1,
            "payload": payload,
            "model_ids": AgyProvider().llm_known_model_names(),
            "provider": context.provider,
            "context_id": context.context_id,
            "account_generation": context.account_generation,
            "request_started_at": float(context.request_started_at),
            "now": _clock_for_context(context),
        }
    )
    if not isinstance(observation, dict):
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="agy_usage_observation_missing",
        )
    return observation


def _status(
    context: UsageProbeContext,
    outcome: UsageCollectionOutcome,
    reason_code: UsageReasonCode | None = None,
    diagnostic: str | None = None,
) -> dict[str, Any]:
    return validated_status_observation(
        context,
        now=_clock_for_context(context),
        outcome=outcome,
        reason_code=reason_code,
        diagnostic=diagnostic,
    )


def _clock_for_context(context: UsageProbeContext) -> float:
    return max(time.time(), context.request_started_at)


def _subprocess_deadline(context: UsageProbeContext) -> float:
    now = time.time()
    remaining = context.deadline_at - now
    if remaining <= _MIN_SUBPROCESS_DEADLINE_SECONDS:
        return context.deadline_at
    return max(
        now + _MIN_SUBPROCESS_DEADLINE_SECONDS,
        context.deadline_at - _SUBPROCESS_CLEANUP_MARGIN_SECONDS,
    )
