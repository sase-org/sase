"""Grok Build ACP billing usage collector."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from collections.abc import Mapping
from typing import Any, Literal

from sase.core.rust import require_rust_binding
from sase.llm_provider.usage._strategy import (
    ProbeStrategy,
    classify_probe_failure,
    run_probe_strategies,
)
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
    "vendor_drift",
]

log = logging.getLogger(__name__)


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
            init_status = _status_from_error(
                init_response, context, method="initialize"
            )
            if init_status is not None:
                return init_status
            return run_probe_strategies(
                context,
                (
                    ProbeStrategy(
                        "billing",
                        lambda attempt_context: _collect_grok_billing(
                            session, attempt_context
                        ),
                    ),
                ),
                logger=log,
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
    except JsonLineTransportError as exc:
        return _transport_status(exc, context)
    raise AssertionError("grok usage collector exited without an observation")


def _collect_grok_billing(
    session: JsonLineSession, context: UsageProbeContext
) -> dict[str, Any]:
    session.send(
        {
            "jsonrpc": "2.0",
            "id": "sase-grok-billing",
            "method": _BILLING_METHOD,
            "params": {},
        }
    )
    billing_response = session.read_response("sase-grok-billing")
    error_status = _status_from_error(billing_response, context, method=_BILLING_METHOD)
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
    return _observation_from_payload(payload, context)


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


def _observation_from_payload(
    payload: Mapping[str, Any],
    context: UsageProbeContext,
) -> dict[str, Any]:
    binding = require_rust_binding("provider_usage_normalize_grok_billing")
    observation = binding(
        {
            "schema_version": 1,
            "payload": dict(payload),
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
            diagnostic="grok_billing_payload_missing",
        )
    return observation


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
    response: Mapping[str, Any], context: UsageProbeContext, *, method: str
) -> dict[str, Any] | None:
    error = response.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    evidence = _evidence_text(error)
    if (
        method == _BILLING_METHOD
        and classify_probe_failure("probe_failed", acp_error=error) == "vendor_drift"
    ):
        return _status(
            context,
            outcome="error",
            reason_code="vendor_drift",
            diagnostic="grok_billing_extension_missing",
        )
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
