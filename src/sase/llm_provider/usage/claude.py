"""Claude Code subscription-usage collection."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from packaging.version import Version

from sase.llm_provider.usage._claude_support import (
    ClaudeAuthInfo,
    ClaudeCommandResult,
    ClaudeCommandRunner,
    auth_info_from_result,
    event_window,
    extract_plan,
    extract_version,
    has_zero_cost_markers,
    hashed_context_id,
    is_finite_number,
    optional_epoch_seconds,
    parse_usage_windows,
    print_help_supports_zero_cost_probe,
    resolve_claude_executable,
    run_claude_command,
    safe_run,
    status_from_auth_text,
    status_observation,
    usage_probe_argv,
    vendor_state_from_rate_limit_info,
)
from sase.llm_provider.usage.config import collection_skip_reason
from sase.llm_provider.usage.probe import record_passive_usage_observation
from sase.llm_provider.usage.store import (
    prepare_provider_usage_account_context,
    record_provider_usage_observation,
)
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    observation_schema_version,
    validate_observation,
)

log = logging.getLogger(__name__)

CLAUDE_PROVIDER_NAME = "claude"
CLAUDE_USAGE_MIN_VERSION = Version("2.1.263")
CLAUDE_PASSIVE_FLUSH_SECONDS = 0.2
CLAUDE_PASSIVE_QUEUE_LIMIT = 8
_run_claude_command: ClaudeCommandRunner = run_claude_command


def collect_claude_usage(
    context: UsageProbeContext,
    *,
    runner: ClaudeCommandRunner | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Collect one zero-inference Claude ``/usage`` observation."""
    executable = resolve_claude_executable(context.executable)
    current = clock()
    if executable is None:
        return status_observation(
            context,
            now=current,
            outcome="unsupported",
            reason_code="not_installed",
        )
    run = runner or _run_claude_command

    preflight = _preflight_usage_probe(context, executable, run, clock)
    if preflight is not None:
        return preflight

    auth_info = _read_claude_auth_info(context, executable, run, clock)
    if auth_info.mode == "api":
        return status_observation(
            context,
            now=clock(),
            outcome="not_applicable",
            reason_code="api_mode",
            account_mode="api",
            plan=auth_info.plan,
        )
    if auth_info.mode == "logged_out":
        return status_observation(
            context,
            now=clock(),
            outcome="unauthenticated",
            reason_code="logged_out",
            plan=auth_info.plan,
        )

    usage_result = safe_run(
        run,
        usage_probe_argv(executable),
        cwd=context.working_directory,
        deadline_at=context.deadline_at,
    )
    if usage_result == "timeout":
        return status_observation(
            context,
            now=clock(),
            outcome="error",
            reason_code="timeout",
        )
    if usage_result == "not_installed":
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="not_installed",
        )
    if usage_result == "failed":
        return status_observation(
            context,
            now=clock(),
            outcome="error",
            reason_code="probe_failed",
        )
    if not isinstance(usage_result, ClaudeCommandResult):
        return status_observation(
            context,
            now=clock(),
            outcome="error",
            reason_code="probe_failed",
        )
    if usage_result.returncode != 0:
        status_from_text = status_from_auth_text(
            f"{usage_result.stdout}\n{usage_result.stderr}"
        )
        if status_from_text.mode == "api":
            return status_observation(
                context,
                now=clock(),
                outcome="not_applicable",
                reason_code="api_mode",
                account_mode="api",
            )
        if status_from_text.mode == "logged_out":
            return status_observation(
                context,
                now=clock(),
                outcome="unauthenticated",
                reason_code="logged_out",
            )
        return status_observation(
            context,
            now=clock(),
            outcome="error",
            reason_code="probe_failed",
        )

    return _observation_from_usage_stdout(
        usage_result.stdout,
        context=context,
        auth_info=auth_info,
        now=clock(),
    )


def capture_claude_passive_usage_context(
    *,
    executable: str | None = None,
    runner: ClaudeCommandRunner | None = None,
    clock: Callable[[], float] = time.time,
) -> UsageProbeContext | None:
    """Prepare a generation-fenced context for Claude stream usage events."""
    if collection_skip_reason(CLAUDE_PROVIDER_NAME) is not None:
        return None
    resolved = resolve_claude_executable(executable)
    if resolved is None:
        return None
    run = runner or _run_claude_command
    now = clock()
    auth_result = safe_run(
        run,
        (resolved, "auth", "status", "--json"),
        cwd=None,
        deadline_at=now + 2.0,
    )
    if not isinstance(auth_result, ClaudeCommandResult):
        return None
    auth_info = auth_info_from_result(auth_result)
    if auth_info.mode != "subscription" or not auth_info.context_material:
        return None
    context_id = hashed_context_id(auth_info.context_material)
    try:
        prepared = prepare_provider_usage_account_context(
            CLAUDE_PROVIDER_NAME,
            context_id,
            now=now,
        )
    except Exception:
        log.debug("Claude passive usage account context was unavailable")
        return None
    return UsageProbeContext(
        schema_version=observation_schema_version(),
        provider=CLAUDE_PROVIDER_NAME,
        deadline_at=now + 2.0,
        context_id=prepared.context_id,
        account_generation=prepared.account_generation,
        operation_id=f"claude-stream-{uuid.uuid4().hex[:12]}",
        request_started_at=now,
        executable=resolved,
        auth_context=context_id,
    )


def _claude_rate_limit_event_observation(
    event: Mapping[str, Any],
    context: UsageProbeContext,
    *,
    now: float,
) -> dict[str, Any] | None:
    """Normalize one Claude ``rate_limit_event`` into a partial observation."""
    if event.get("type") != "rate_limit_event" or context.provider != "claude":
        return None
    info = event.get("rate_limit_info")
    if not isinstance(info, Mapping):
        return None
    raw_windows = info.get("unifiedWindows")
    if not isinstance(raw_windows, Mapping):
        return None

    windows: list[dict[str, Any]] = []
    malformed = False
    for raw_key, raw_window in raw_windows.items():
        if not isinstance(raw_key, str) or not isinstance(raw_window, Mapping):
            malformed = True
            continue
        utilization = raw_window.get("utilization")
        if (
            isinstance(utilization, bool)
            or not isinstance(utilization, int | float)
            or not is_finite_number(utilization)
        ):
            malformed = True
            continue
        utilization_value = float(utilization)
        if utilization_value < 0.0:
            malformed = True
            continue
        resets_at = optional_epoch_seconds(raw_window.get("resetsAt"))
        if resets_at == "malformed":
            malformed = True
            resets_at = None
        window = event_window(raw_key, utilization_value * 100.0, resets_at, now)
        window["vendor_state"] = vendor_state_from_rate_limit_info(info)
        windows.append(window)

    if not windows:
        return None
    observation = {
        "schema_version": context.schema_version,
        "provider": CLAUDE_PROVIDER_NAME,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": now,
        "received_at": now,
        "source": "stream_event",
        "outcome": "ok",
        "reason_code": "parse_error" if malformed else None,
        "diagnostic": (
            "some Claude rate-limit windows could not be parsed" if malformed else None
        ),
        "completeness": "partial",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": None,
        "windows": windows,
    }
    try:
        return validate_observation(observation, now=now)
    except (TypeError, ValueError, AttributeError):
        return None


def submit_claude_passive_usage_event(
    event: Mapping[str, Any],
    context: UsageProbeContext | None,
) -> None:
    """Queue a Claude stream event for best-effort usage persistence."""
    if context is None:
        return
    try:
        observation = _claude_rate_limit_event_observation(
            event,
            context,
            now=time.time(),
        )
    except Exception:
        log.debug("Claude passive usage event was ignored")
        return
    if observation is not None:
        _PASSIVE_SINK.submit(observation)


def flush_claude_passive_usage_events(
    timeout: float = CLAUDE_PASSIVE_FLUSH_SECONDS,
) -> None:
    """Best-effort bounded flush for queued Claude usage stream events."""
    _PASSIVE_SINK.flush(timeout)


def _preflight_usage_probe(
    context: UsageProbeContext,
    executable: str,
    run: ClaudeCommandRunner,
    clock: Callable[[], float],
) -> dict[str, Any] | None:
    version_result = safe_run(
        run,
        (executable, "--version"),
        cwd=None,
        deadline_at=context.deadline_at,
    )
    if version_result == "timeout":
        return status_observation(
            context, now=clock(), outcome="error", reason_code="timeout"
        )
    if version_result == "not_installed":
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="not_installed",
        )
    if (
        not isinstance(version_result, ClaudeCommandResult)
        or version_result.returncode != 0
    ):
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )
    version = extract_version(f"{version_result.stdout} {version_result.stderr}")
    if version is None or version < CLAUDE_USAGE_MIN_VERSION:
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )

    print_help = safe_run(
        run,
        (executable, "-p", "--help"),
        cwd=None,
        deadline_at=context.deadline_at,
    )
    auth_help = safe_run(
        run,
        (executable, "auth", "status", "--help"),
        cwd=None,
        deadline_at=context.deadline_at,
    )
    if print_help == "timeout" or auth_help == "timeout":
        return status_observation(
            context, now=clock(), outcome="error", reason_code="timeout"
        )
    if print_help == "not_installed" or auth_help == "not_installed":
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="not_installed",
        )
    if not (
        isinstance(print_help, ClaudeCommandResult)
        and isinstance(auth_help, ClaudeCommandResult)
        and print_help.returncode == 0
        and auth_help.returncode == 0
        and print_help_supports_zero_cost_probe(print_help.stdout)
        and "--json" in auth_help.stdout
    ):
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )
    return None


def _read_claude_auth_info(
    context: UsageProbeContext,
    executable: str,
    run: ClaudeCommandRunner,
    clock: Callable[[], float],
) -> ClaudeAuthInfo:
    result = safe_run(
        run,
        (executable, "auth", "status", "--json"),
        cwd=None,
        deadline_at=min(context.deadline_at, clock() + 2.0),
    )
    if not isinstance(result, ClaudeCommandResult):
        return ClaudeAuthInfo(mode=None)
    return auth_info_from_result(result)


def _observation_from_usage_stdout(
    stdout: str,
    *,
    context: UsageProbeContext,
    auth_info: ClaudeAuthInfo,
    now: float,
) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        text_status = status_from_auth_text(stdout)
        if text_status.mode == "api":
            return status_observation(
                context,
                now=now,
                outcome="not_applicable",
                reason_code="api_mode",
                account_mode="api",
            )
        if text_status.mode == "logged_out":
            return status_observation(
                context,
                now=now,
                outcome="unauthenticated",
                reason_code="logged_out",
            )
        return status_observation(
            context, now=now, outcome="error", reason_code="parse_error"
        )
    if not isinstance(payload, Mapping):
        return status_observation(
            context, now=now, outcome="error", reason_code="malformed_payload"
        )
    if not has_zero_cost_markers(payload):
        return status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="probe_failed",
            diagnostic="Claude usage probe did not prove zero-turn zero-cost execution",
        )
    result_text = payload.get("result")
    if not isinstance(result_text, str):
        return status_observation(
            context, now=now, outcome="error", reason_code="parse_error"
        )
    text_status = status_from_auth_text(result_text)
    windows, had_parse_error = parse_usage_windows(
        result_text,
        observed_at=context.request_started_at,
    )
    if not windows:
        if text_status.mode == "api":
            return status_observation(
                context,
                now=now,
                outcome="not_applicable",
                reason_code="api_mode",
                account_mode="api",
                plan=auth_info.plan,
            )
        if text_status.mode == "logged_out":
            return status_observation(
                context,
                now=now,
                outcome="unauthenticated",
                reason_code="logged_out",
                plan=auth_info.plan,
            )
        return status_observation(
            context, now=now, outcome="error", reason_code="parse_error"
        )

    observation = {
        "schema_version": context.schema_version,
        "provider": CLAUDE_PROVIDER_NAME,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": context.request_started_at,
        "received_at": max(now, context.request_started_at),
        "source": "probe",
        "outcome": "ok",
        "reason_code": "parse_error" if had_parse_error else None,
        "diagnostic": (
            "some Claude usage rows could not be parsed" if had_parse_error else None
        ),
        "completeness": "partial" if had_parse_error else "complete",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": auth_info.plan or extract_plan(result_text),
        "windows": windows,
    }
    try:
        return validate_observation(
            observation,
            now=max(now, context.request_started_at),
        )
    except (TypeError, ValueError, AttributeError):
        return status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="malformed_payload",
        )


class _PassiveUsageSink:
    """Bounded background sink for stream-fed usage observations."""

    def __init__(self) -> None:
        self._pending: deque[Mapping[str, Any]] = deque()
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = 0

    def submit(self, observation: Mapping[str, Any]) -> None:
        with self._lock:
            if len(self._pending) >= CLAUDE_PASSIVE_QUEUE_LIMIT:
                self._pending.popleft()
            self._pending.append(dict(observation))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="sase-claude-passive-usage",
                    daemon=True,
                )
                self._thread.start()
            self._event.set()

    def flush(self, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            with self._lock:
                if not self._pending and self._active == 0:
                    return
            time.sleep(0.01)

    def _run(self) -> None:
        while True:
            self._event.wait()
            while True:
                with self._lock:
                    if not self._pending:
                        self._event.clear()
                        break
                    observation = self._pending.popleft()
                    self._active += 1
                try:
                    _persist_passive_observation(observation)
                finally:
                    with self._lock:
                        self._active -= 1


def _persist_passive_observation(observation: Mapping[str, Any]) -> None:
    try:
        validated = record_passive_usage_observation(observation, now=time.time())
        if validated is not None:
            record_provider_usage_observation(validated, now=time.time())
    except Exception:
        log.debug("Claude passive usage observation could not be persisted")


_PASSIVE_SINK = _PassiveUsageSink()


__all__ = [
    "CLAUDE_PROVIDER_NAME",
    "CLAUDE_USAGE_MIN_VERSION",
    "capture_claude_passive_usage_context",
    "collect_claude_usage",
    "flush_claude_passive_usage_events",
    "submit_claude_passive_usage_event",
]
