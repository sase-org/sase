"""Active Claude ``/usage`` probe collection."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from sase.llm_provider.usage._capability_cache import executable_fingerprint
from sase.llm_provider.usage._claude_constants import CLAUDE_PROVIDER_NAME
from sase.llm_provider.usage._claude_preflight import preflight_usage_probe
from sase.llm_provider.usage._claude_support import (
    ClaudeAuthInfo,
    ClaudeCommandResult,
    ClaudeCommandRunner,
    auth_info_from_result,
    extract_plan,
    has_zero_cost_markers,
    parse_usage_windows,
    resolve_claude_executable,
    safe_run,
    status_from_auth_text,
    status_observation,
    usage_probe_argv,
)
from sase.llm_provider.usage._strategy import (
    ProbeStrategy,
    classify_probe_failure,
    detect_rate_limit,
    run_probe_strategies,
)
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    bounded_probe_diagnostic,
    validate_observation,
)

log = logging.getLogger(__name__)


def run_claude_probe(
    context: UsageProbeContext,
    *,
    run: ClaudeCommandRunner,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Run the Claude probe with an already-resolved command runner."""
    executable = resolve_claude_executable(context.executable)
    current = clock()
    if executable is None:
        return status_observation(
            context,
            now=current,
            outcome="unsupported",
            reason_code="not_installed",
        )

    preflight = preflight_usage_probe(
        context,
        executable,
        run,
        clock,
        fingerprint=executable_fingerprint(executable),
    )
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

    return run_probe_strategies(
        context,
        (
            ProbeStrategy(
                "usage",
                lambda attempt_context: _collect_claude_usage_strategy(
                    attempt_context,
                    executable=executable,
                    run=run,
                    clock=clock,
                    auth_info=auth_info,
                ),
            ),
        ),
        logger=log,
    )


def _collect_claude_usage_strategy(
    context: UsageProbeContext,
    *,
    executable: str,
    run: ClaudeCommandRunner,
    clock: Callable[[], float],
    auth_info: ClaudeAuthInfo,
) -> dict[str, Any]:
    """Run the single guarded Claude usage strategy."""
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
            diagnostic=bounded_probe_diagnostic("claude /usage failed before exit"),
        )
    if not isinstance(usage_result, ClaudeCommandResult):
        return status_observation(
            context,
            now=clock(),
            outcome="error",
            reason_code="probe_failed",
            diagnostic=bounded_probe_diagnostic(
                "claude /usage returned an unexpected command result"
            ),
        )
    if usage_result.returncode != 0:
        limited = detect_rate_limit(
            command_returncode=usage_result.returncode,
            stdout=usage_result.stdout,
            stderr=usage_result.stderr,
        )
        if limited is not None:
            return status_observation(
                context,
                now=clock(),
                outcome="error",
                reason_code="rate_limited",
                diagnostic=_claude_usage_exit_diagnostic(usage_result),
                retry_after_seconds=limited.retry_after_seconds,
            )
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
        reason_code = classify_probe_failure(
            "probe_failed",
            command_returncode=usage_result.returncode,
            stdout=usage_result.stdout,
            stderr=usage_result.stderr,
        )
        return status_observation(
            context,
            now=clock(),
            outcome="error",
            reason_code=reason_code,
            diagnostic=_claude_usage_exit_diagnostic(usage_result),
        )

    return _observation_from_usage_stdout(
        usage_result.stdout,
        context=context,
        auth_info=auth_info,
        now=clock(),
    )


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
        limited = detect_rate_limit(stdout=stdout)
        if limited is not None:
            return status_observation(
                context,
                now=now,
                outcome="error",
                reason_code="rate_limited",
                retry_after_seconds=limited.retry_after_seconds,
            )
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
    windows, parse_diagnostic = parse_usage_windows(
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
        "reason_code": "parse_error" if parse_diagnostic else None,
        "diagnostic": parse_diagnostic,
        "completeness": "partial" if parse_diagnostic else "complete",
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


def _claude_usage_exit_diagnostic(result: ClaudeCommandResult) -> str:
    detail = _first_nonempty_line(result.stderr) or _first_nonempty_line(result.stdout)
    suffix = f": {detail}" if detail else ""
    return bounded_probe_diagnostic(f"claude /usage exited {result.returncode}{suffix}")


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


__all__ = [
    "run_claude_probe",
]
