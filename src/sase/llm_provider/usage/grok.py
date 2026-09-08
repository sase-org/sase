"""Grok Build ACP billing usage collector."""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sase.llm_provider.usage.transport import JsonLineSession, JsonLineTransportError
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    validated_status_observation,
)

_GROK_VERSION_RE = re.compile(r"^grok \d+\.\d+\.\d+ \([0-9a-f]+\) \[[a-z]+\]")
_VERSION_PROBE_TIMEOUT_SECONDS = 2.0
_SUBPROCESS_CLEANUP_MARGIN_SECONDS = 0.25
_MIN_SUBPROCESS_DEADLINE_SECONDS = 0.1
# ACP extension methods take a `_` wire prefix. `x.ai/billing` returns -32601.
_BILLING_METHOD = "_x.ai/billing"
_Outcome = Literal["ok", "not_applicable", "unauthenticated", "unsupported", "error"]
_ReasonCode = Literal[
    "not_installed",
    "unsupported_cli_version",
    "timeout",
    "parse_error",
    "account_context_changed",
    "logged_out",
    "api_mode",
    "malformed_payload",
    "deadline_exceeded",
    "probe_failed",
]


def collect_grok_usage(
    context: UsageProbeContext, executable: str | None = None
) -> dict[str, Any]:
    """Collect Grok included subscription usage through the Grok Build ACP extension."""
    command = executable or context.executable or "grok"
    identity_status = _verify_grok_build(command, context)
    if identity_status is not None:
        return identity_status
    try:
        with JsonLineSession(
            (command, "--no-auto-update", "agent", "stdio"),
            deadline_at=_subprocess_deadline(context),
            cwd=context.working_directory,
        ) as session:
            session.send(_initialize_request())
            init_response = session.read_response("sase-grok-init")
            init_status = _status_from_error(init_response, context)
            if init_status is not None:
                return init_status
            session.send(
                {
                    "jsonrpc": "2.0",
                    "id": "sase-grok-billing",
                    "method": _BILLING_METHOD,
                    "params": {},
                }
            )
            billing_response = session.read_response("sase-grok-billing")
    except FileNotFoundError:
        return _status(
            context,
            outcome="error",
            reason_code="not_installed",
            diagnostic="grok_executable_not_found",
        )
    except OSError:
        return _status(
            context,
            outcome="unsupported",
            reason_code="unsupported_cli_version",
            diagnostic="grok_executable_identity_mismatch",
        )
    except JsonLineTransportError as exc:
        return _transport_status(exc, context)
    error_status = _status_from_error(billing_response, context)
    if error_status is not None:
        return error_status
    payload = _billing_payload(billing_response)
    if payload is None:
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="grok_billing_payload_missing",
        )
    not_applicable = _not_applicable_status(payload, context)
    if not_applicable is not None:
        return not_applicable
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="grok_billing_config_missing",
        )
    return _observation_from_config(config, payload, context)


def _initialize_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "sase-grok-init",
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {}, "terminal": False},
            "_meta": {
                "startupHints": {
                    "nonInteractive": True,
                    "skipGitStatus": True,
                    "skipProjectLayout": True,
                },
                "clientType": "sase",
                "clientVersion": "0.0",
            },
        },
    }


def _verify_grok_build(
    executable: str, context: UsageProbeContext
) -> dict[str, Any] | None:
    if time.time() >= context.deadline_at:
        return _status(
            context,
            outcome="error",
            reason_code="deadline_exceeded",
            diagnostic="grok_version_probe_deadline_exceeded",
        )
    timeout = max(
        0.1,
        min(_VERSION_PROBE_TIMEOUT_SECONDS, context.deadline_at - time.time()),
    )
    try:
        completed = subprocess.run(
            [executable, "--version"],
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
            diagnostic="grok_executable_not_found",
        )
    except OSError:
        return _status(
            context,
            outcome="unsupported",
            reason_code="unsupported_cli_version",
            diagnostic="grok_executable_identity_mismatch",
        )
    except subprocess.TimeoutExpired:
        return _status(
            context,
            outcome="error",
            reason_code="timeout",
            diagnostic="grok_version_probe_timeout",
        )
    version_line = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not version_line:
        return _status(
            context,
            outcome="unsupported",
            reason_code="unsupported_cli_version",
            diagnostic="grok_version_probe_failed",
        )
    if not _GROK_VERSION_RE.match(version_line[0]):
        return _status(
            context,
            outcome="unsupported",
            reason_code="unsupported_cli_version",
            diagnostic="grok_executable_identity_mismatch",
        )
    return None


def _billing_payload(response: Mapping[str, Any]) -> Mapping[str, Any] | None:
    result = response.get("result")
    if isinstance(result, str):
        try:
            decoded = json.loads(result)
        except json.JSONDecodeError:
            return None
        result = decoded
    if not isinstance(result, Mapping):
        return None
    nested_result = result.get("result")
    if "config" not in result and isinstance(nested_result, Mapping):
        return nested_result
    return result


def _observation_from_config(
    config: Mapping[str, Any],
    payload: Mapping[str, Any],
    context: UsageProbeContext,
) -> dict[str, Any]:
    usage_percent = _usage_percent(config)
    if usage_percent is None:
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="grok_billing_usage_percent_missing",
        )
    period = _billing_period(config)
    completeness = "complete"
    diagnostic = "grok_build_billing_first_party_unstable"
    if period.resets_at is None:
        completeness = "partial"
        diagnostic = "grok_billing_period_missing_reset"
    window = {
        "key": period.key,
        "label": period.label,
        "used_percent": usage_percent,
        "resets_at": period.resets_at,
        "duration_seconds": period.duration_seconds,
        "period_start": period.period_start,
        "applicability": {"kind": "account"},
        "observed_at": _clock_for_context(context),
        "source": "probe",
        "vendor_state": "unknown",
    }
    return {
        "schema_version": context.schema_version,
        "provider": context.provider,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": float(context.request_started_at),
        "received_at": _clock_for_context(context),
        "source": "probe",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": diagnostic,
        "completeness": completeness,
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": _string_or_none(payload.get("subscriptionTier"))
        or _string_or_none(config.get("subscriptionTier")),
        "windows": [window],
    }


class _Period:
    def __init__(
        self,
        key: str,
        label: str,
        resets_at: float | None,
        duration_seconds: float | None,
        period_start: float | None,
    ) -> None:
        self.key = key
        self.label = label
        self.resets_at = resets_at
        self.duration_seconds = duration_seconds
        self.period_start = period_start


def _billing_period(config: Mapping[str, Any]) -> _Period:
    current_period = config.get("currentPeriod")
    period_kind = None
    start_value = None
    end_value = None
    if isinstance(current_period, Mapping):
        period_kind = _period_kind(current_period.get("type"))
        start_value = current_period.get("start")
        end_value = current_period.get("end")
    if period_kind is None:
        start_value = start_value or config.get("billingPeriodStart")
        end_value = end_value or config.get("billingPeriodEnd")
        if start_value is not None or end_value is not None:
            period_kind = "monthly"
    period_start = _timestamp(start_value)
    resets_at = _timestamp(end_value)
    duration_seconds = None
    if period_start is not None and resets_at is not None and resets_at > period_start:
        duration_seconds = resets_at - period_start
    if period_kind == "weekly":
        return _Period(
            key="included_weekly",
            label="Grok included weekly allowance",
            resets_at=resets_at,
            duration_seconds=duration_seconds,
            period_start=period_start,
        )
    if period_kind == "monthly":
        return _Period(
            key="included_monthly",
            label="Grok included monthly allowance",
            resets_at=resets_at,
            duration_seconds=duration_seconds,
            period_start=period_start,
        )
    return _Period(
        key="included",
        label="Grok included allowance",
        resets_at=resets_at,
        duration_seconds=duration_seconds,
        period_start=period_start,
    )


def _usage_percent(config: Mapping[str, Any]) -> float | None:
    if "creditUsagePercent" in config:
        return _finite_nonnegative_number(config.get("creditUsagePercent"))
    used = _cent_value(config.get("used"))
    limit = _cent_value(config.get("monthlyLimit"))
    if used is None or limit is None or limit <= 0:
        return None
    return (used / limit) * 100.0


def _cent_value(value: Any) -> float | None:
    if not isinstance(value, Mapping):
        return None
    return _finite_nonnegative_number(value.get("val"))


def _finite_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _period_kind(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    if "weekly" in normalized or "week" in normalized:
        return "weekly"
    if "monthly" in normalized or "month" in normalized:
        return "monthly"
    return None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        if math.isfinite(number):
            return number
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _not_applicable_status(
    payload: Mapping[str, Any], context: UsageProbeContext
) -> dict[str, Any] | None:
    evidence = _evidence_text(payload)
    if _contains_any(evidence, ("api key", "api_key", "api mode", "api-mode")):
        return _status(
            context,
            outcome="not_applicable",
            reason_code="api_mode",
            diagnostic="grok_subscription_usage_not_available_for_api_auth",
        )
    if _contains_any(
        evidence,
        (
            "enterprise",
            "free",
            "ineligible",
            "not eligible",
            "not_applicable",
            "not applicable",
            "no subscription",
            "no_subscription",
            "unsupported plan",
        ),
    ):
        return _status(
            context,
            outcome="not_applicable",
            diagnostic="grok_subscription_usage_not_applicable",
        )
    return None


def _status_from_error(
    response: Mapping[str, Any], context: UsageProbeContext
) -> dict[str, Any] | None:
    error = response.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    evidence = _evidence_text(error)
    if code == -32601 or _contains_any(
        evidence, ("method not found", "method_not_found", "unknown method")
    ):
        return _status(
            context,
            outcome="unsupported",
            reason_code="unsupported_cli_version",
            diagnostic="grok_billing_extension_missing",
        )
    if _contains_any(evidence, ("api key", "api_key", "api mode", "api-mode")):
        return _status(
            context,
            outcome="not_applicable",
            reason_code="api_mode",
            diagnostic="grok_subscription_usage_not_available_for_api_auth",
        )
    if _contains_any(
        evidence,
        (
            "auth_required",
            "authenticate",
            "authenticated",
            "log in",
            "logged in",
            "login",
        ),
    ):
        return _status(
            context,
            outcome="unauthenticated",
            reason_code="logged_out",
            diagnostic="grok_billing_auth_required",
        )
    if _contains_any(evidence, ("enterprise", "free", "ineligible", "not eligible")):
        return _status(
            context,
            outcome="not_applicable",
            diagnostic="grok_subscription_usage_not_applicable",
        )
    return _status(
        context,
        outcome="error",
        reason_code="probe_failed",
        diagnostic="grok_billing_extension_error",
    )


def _transport_status(
    exc: JsonLineTransportError, context: UsageProbeContext
) -> dict[str, Any]:
    if exc.code == "timeout":
        return _status(
            context,
            outcome="error",
            reason_code="timeout",
            diagnostic="grok_acp_probe_timeout",
        )
    if exc.code == "malformed_response":
        return _status(
            context,
            outcome="error",
            reason_code="parse_error",
            diagnostic="grok_acp_malformed_response",
        )
    if exc.code == "deadline_exceeded":
        return _status(
            context,
            outcome="error",
            reason_code="deadline_exceeded",
            diagnostic="grok_acp_deadline_exceeded",
        )
    return _status(
        context,
        outcome="error",
        reason_code="probe_failed",
        diagnostic=f"grok_acp_{exc.code}",
    )


def _status(
    context: UsageProbeContext,
    outcome: _Outcome,
    reason_code: _ReasonCode | None = None,
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


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _evidence_text(value: Any) -> str:
    parts: list[str] = []
    _collect_evidence(value, parts)
    return " ".join(parts).lower()


def _collect_evidence(value: Any, parts: list[str]) -> None:
    if isinstance(value, str):
        parts.append(value)
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                parts.append(key)
            _collect_evidence(child, parts)
        return
    if isinstance(value, list | tuple):
        for child in value:
            _collect_evidence(child, parts)


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
