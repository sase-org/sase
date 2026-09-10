"""Codex subscription-usage collector: bounded ``codex app-server`` session.

Speaks the app-server JSON-RPC protocol over stdio directly (``initialize`` ->
``initialized`` -> best-effort ``account/read`` -> ``account/rateLimits/read``).
Never opens ``auth.json`` and never treats normal ``codex exec --json`` token
events as subscription capacity (epic sase-y5 plan).
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Mapping
from typing import Any

from sase import __version__ as _SASE_VERSION

from ..codex import resolve_codex_executable
from ._strategy import ProbeStrategy, classify_probe_failure, run_probe_strategies
from .probe import worker_environ
from .transport import JsonLineSession, JsonLineTransportError
from .types import (
    UsageProbeContext,
    UsageReasonCode,
    bounded_probe_diagnostic,
    validate_observation,
    validated_status_observation,
)

_INITIALIZE_ID = 1
_ACCOUNT_READ_ID = 2
_RATE_LIMITS_ID = 3
_RATE_LIMITS_LEGACY_ID = 4
_RATE_LIMITS_METHOD = "account/rateLimits/read"

_UNAUTHENTICATED_MARKERS = (
    "not logged in",
    "not authenticated",
    "unauthenticated",
    "unauthorized",
    "sign in",
    "no active account",
    "no account",
)

# The exact ``account/read`` response schema is not independently verified —
# research evidence only verified ``account/rateLimits/read`` live (epic
# sase-y5 plan, research:202609/provider_subscription_usage). These are the
# most plausible field/value names; any mismatch degrades to "inconclusive"
# rather than blocking collection. PROPOSED FOLLOW-UP: confirm against a live
# ``codex app-server`` response and tighten this once verified.
_AUTH_MODE_KEYS = ("authMode", "auth_mode", "mode", "accountType", "account_type")
_API_MODE_HINTS = ("apikey", "api_key", "api-key", "api")
_CHATGPT_MODE_HINTS = ("chatgpt", "subscription", "oauth")

_TRANSPORT_REASON_BY_CODE: dict[str, UsageReasonCode] = {
    "timeout": "timeout",
    "malformed_response": "parse_error",
}

log = logging.getLogger(__name__)


def collect_codex_usage(context: UsageProbeContext) -> dict[str, Any]:
    """Collect one Codex subscription-usage observation through app-server."""
    executable = context.executable or resolve_codex_executable()
    argv = (executable, "app-server")
    env = worker_environ()
    tmp_cwd: tempfile.TemporaryDirectory[str] | None = None
    cwd = context.working_directory
    if not cwd:
        tmp_cwd = tempfile.TemporaryDirectory(prefix="sase-codex-usage-")
        cwd = tmp_cwd.name
    try:
        session = JsonLineSession(
            argv, deadline_at=context.deadline_at, cwd=cwd, env=env
        )
    except OSError:
        if tmp_cwd is not None:
            tmp_cwd.cleanup()
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="unsupported",
            reason_code="not_installed",
        )
    try:
        return _collect_with_session(session, context)
    except JsonLineTransportError as exc:
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="error",
            reason_code=_TRANSPORT_REASON_BY_CODE.get(exc.code, "probe_failed"),
        )
    finally:
        session.close()
        if tmp_cwd is not None:
            tmp_cwd.cleanup()


def _collect_with_session(
    session: JsonLineSession, context: UsageProbeContext
) -> dict[str, Any]:
    session.send(
        {
            "jsonrpc": "2.0",
            "id": _INITIALIZE_ID,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "sase",
                    "title": "SASE",
                    "version": _SASE_VERSION,
                }
            },
        }
    )
    init_response = session.read_response(_INITIALIZE_ID)
    init_error = _rpc_error(init_response)
    if init_error is not None:
        return _observation_from_error(context, "initialize", init_error)
    session.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    if _probe_auth_mode(session) == "api":
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="not_applicable",
            reason_code="api_mode",
        )

    return run_probe_strategies(
        context,
        (
            ProbeStrategy(
                "no_params",
                lambda attempt_context: _collect_rate_limits(
                    session,
                    attempt_context,
                    request_id=_RATE_LIMITS_ID,
                    params=None,
                ),
            ),
            ProbeStrategy(
                "legacy_params",
                lambda attempt_context: _collect_rate_limits(
                    session,
                    attempt_context,
                    request_id=_RATE_LIMITS_LEGACY_ID,
                    params={"excludeResetCreditDetails": True},
                ),
            ),
        ),
        logger=log,
    )


def _probe_auth_mode(session: JsonLineSession) -> str | None:
    """Best-effort ``account/read`` auth-mode hint; ``None`` is inconclusive."""
    try:
        session.send(
            {
                "jsonrpc": "2.0",
                "id": _ACCOUNT_READ_ID,
                "method": "account/read",
                "params": {},
            }
        )
        response = session.read_response(_ACCOUNT_READ_ID)
    except JsonLineTransportError:
        return None
    if _rpc_error(response) is not None:
        return None
    return _extract_auth_mode_hint(response.get("result"))


def _extract_auth_mode_hint(result: object) -> str | None:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(result, dict):
        candidates.append(result)
        nested = result.get("account")
        if isinstance(nested, dict):
            candidates.append(nested)
    for mapping in candidates:
        for key in _AUTH_MODE_KEYS:
            value = mapping.get(key)
            if not isinstance(value, str):
                continue
            lowered = value.lower()
            is_api = any(hint in lowered for hint in _API_MODE_HINTS)
            is_chatgpt = any(hint in lowered for hint in _CHATGPT_MODE_HINTS)
            if is_api and not is_chatgpt:
                return "api"
            if is_chatgpt:
                return "chatgpt"
    return None


def _collect_rate_limits(
    session: JsonLineSession,
    context: UsageProbeContext,
    *,
    request_id: int,
    params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": _RATE_LIMITS_METHOD,
    }
    if params is not None:
        payload["params"] = dict(params)
    session.send(payload)
    response = session.read_response(request_id)
    error = _rpc_error(response)
    if error is not None:
        return _observation_from_error(context, _RATE_LIMITS_METHOD, error)
    result = response.get("result")
    if not isinstance(result, dict):
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="error",
            reason_code="malformed_payload",
        )
    return _observation_from_rate_limits(context, result)


def _rpc_error(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    error = payload.get("error")
    return error if isinstance(error, dict) else None


def _observation_from_error(
    context: UsageProbeContext, method: str, error: Mapping[str, Any]
) -> dict[str, Any]:
    message = str(error.get("message") or "").lower()
    diagnostic = _rpc_error_diagnostic(method, error)
    if any(marker in message for marker in _UNAUTHENTICATED_MARKERS):
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="unauthenticated",
            reason_code="logged_out",
            diagnostic=diagnostic,
        )
    reason_code = classify_probe_failure(
        "probe_failed",
        json_rpc_error=error,
    )
    return validated_status_observation(
        context,
        now=context.request_started_at,
        outcome="error",
        reason_code=reason_code,
        diagnostic=diagnostic,
    )


def _rpc_error_diagnostic(method: str, error: Mapping[str, Any]) -> str:
    code = error.get("code")
    message = str(error.get("message") or "").strip()
    suffix = f": {message}" if message else ""
    return bounded_probe_diagnostic(f"app-server {method} error {code}{suffix}")


def _observation_from_rate_limits(
    context: UsageProbeContext, result: Mapping[str, Any]
) -> dict[str, Any]:
    buckets = _buckets_from_result(result)
    if not buckets:
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="error",
            reason_code="malformed_payload",
        )
    windows: list[dict[str, Any]] = []
    malformed_count = 0
    plan: str | None = None
    for limit_id, bucket in buckets:
        if (
            not isinstance(limit_id, str)
            or not limit_id
            or not isinstance(bucket, dict)
        ):
            malformed_count += 1
            continue
        bucket_windows, bucket_plan = _windows_from_bucket(context, limit_id, bucket)
        if not bucket_windows:
            malformed_count += 1
        windows.extend(bucket_windows)
        if plan is None and bucket_plan:
            plan = bucket_plan
    if not windows:
        return validated_status_observation(
            context,
            now=context.request_started_at,
            outcome="error",
            reason_code="parse_error",
        )
    completeness = "partial" if malformed_count else "complete"
    observation = {
        "schema_version": context.schema_version,
        "provider": context.provider,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": context.request_started_at,
        "received_at": context.request_started_at,
        "source": "probe",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": (
            f"{malformed_count} Codex rate-limit bucket(s) could not be parsed"
            if malformed_count
            else None
        ),
        "completeness": completeness,
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": plan,
        "windows": windows,
    }
    return validate_observation(observation, now=context.request_started_at)


def _buckets_from_result(result: Mapping[str, Any]) -> list[tuple[str, Any]]:
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and by_id:
        return list(by_id.items())
    legacy = result.get("rateLimits")
    if isinstance(legacy, dict):
        limit_id = legacy.get("limitId")
        if isinstance(limit_id, str) and limit_id:
            return [(limit_id, legacy)]
    return []


def _windows_from_bucket(
    context: UsageProbeContext, limit_id: str, bucket: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], str | None]:
    label = _bucket_label(limit_id, bucket.get("limitName"))
    vendor_state = "rejected" if bucket.get("rateLimitReachedType") else "allowed"
    # Never infer model applicability from a bucket id or label substring
    # (epic sase-y5 plan): only the shared default bucket is declared
    # account-wide; every other bucket keeps its vendor label/id as unknown
    # scope until a verified id->model mapping exists.
    applicability: dict[str, Any] = (
        {"kind": "account"}
        if limit_id == "codex"
        else {
            "kind": "unknown",
            "vendor_label": _clean_optional_str(bucket.get("limitName")),
            "vendor_id": limit_id,
        }
    )
    plan = _clean_optional_str(bucket.get("planType"))
    windows: list[dict[str, Any]] = []
    for slot in ("primary", "secondary"):
        window = _window_from_slot(
            context,
            limit_id,
            slot,
            bucket.get(slot),
            label,
            vendor_state,
            applicability,
        )
        if window is not None:
            windows.append(window)
    return windows, plan


def _window_from_slot(
    context: UsageProbeContext,
    limit_id: str,
    slot: str,
    slot_data: object,
    label: str,
    vendor_state: str,
    applicability: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(slot_data, dict):
        return None
    used_percent = _finite_number(slot_data.get("usedPercent"))
    if used_percent is None:
        return None
    resets_at = _finite_number(slot_data.get("resetsAt"))
    duration_minutes = _finite_number(slot_data.get("windowDurationMins"))
    duration_seconds = duration_minutes * 60.0 if duration_minutes is not None else None
    return {
        "key": f"{limit_id}:{slot}",
        "label": label,
        "used_percent": used_percent,
        "resets_at": resets_at,
        "duration_seconds": duration_seconds,
        "period_start": None,
        "applicability": dict(applicability),
        "observed_at": context.request_started_at,
        "source": "probe",
        "vendor_state": vendor_state,
    }


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _bucket_label(limit_id: str, limit_name: object) -> str:
    cleaned = _clean_optional_str(limit_name)
    if cleaned:
        return cleaned
    return "Codex" if limit_id == "codex" else limit_id


def _clean_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
