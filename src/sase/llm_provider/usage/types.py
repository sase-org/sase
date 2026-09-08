"""Typed probe context and observation helpers for subscription usage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
from collections.abc import Mapping

from sase.core.rust import require_rust_binding

UsageCollectionOutcome = Literal[
    "ok",
    "not_applicable",
    "unauthenticated",
    "unsupported",
    "error",
]
UsageReasonCode = Literal[
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
UsageCompleteness = Literal["complete", "partial"]
UsageSource = Literal["probe", "stream_event"]
UsageSkipReason = Literal["flag_disabled", "config_disabled", "provider_disabled"]

_DIAGNOSTIC_BY_REASON: dict[str, str] = {
    "not_installed": "provider CLI is not installed",
    "unsupported_cli_version": "provider CLI version is unsupported",
    "timeout": "usage probe timed out",
    "parse_error": "usage probe payload could not be parsed",
    "account_context_changed": "provider account context changed",
    "logged_out": "provider is logged out",
    "api_mode": "provider is in API mode",
    "malformed_payload": "usage probe payload was malformed",
    "deadline_exceeded": "usage probe exceeded its deadline",
    "probe_failed": "usage probe failed",
    "unsupported": "provider does not collect subscription usage",
    "flag_disabled": "subscription usage collection is disabled",
    "config_disabled": "subscription usage collection is disabled",
    "provider_disabled": "subscription usage collection is disabled for this provider",
}


@dataclass(frozen=True)
class UsageProbeContext:
    """Inputs supplied to ``llm_usage_probe``.

    ``auth_context`` is an opaque fingerprint. It must not carry secrets,
    account ids, emails, tokens, or filesystem credential paths.
    """

    schema_version: int
    provider: str
    deadline_at: float
    context_id: str
    account_generation: int
    operation_id: str
    request_started_at: float
    executable: str | None = None
    auth_context: str = ""
    working_directory: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        return asdict(self)

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> UsageProbeContext:
        """Rehydrate a context from a worker request mapping."""
        return cls(
            schema_version=int(payload["schema_version"]),
            provider=str(payload["provider"]),
            deadline_at=float(payload["deadline_at"]),
            context_id=str(payload["context_id"]),
            account_generation=int(payload["account_generation"]),
            operation_id=str(payload["operation_id"]),
            request_started_at=float(payload["request_started_at"]),
            executable=_optional_str(payload.get("executable")),
            auth_context=str(payload.get("auth_context") or ""),
            working_directory=_optional_str(payload.get("working_directory")),
        )


@dataclass(frozen=True)
class UsageProbeResult:
    """Outcome of a probe attempt, including collection opt-out."""

    observation: dict[str, Any] | None = None
    skipped: UsageSkipReason | None = None


def observation_schema_version() -> int:
    """Return the core observation schema version."""
    return int(require_rust_binding("provider_usage_observation_schema_version")())


def validate_observation(
    observation: Mapping[str, Any], *, now: float
) -> dict[str, Any]:
    """Validate *observation* through the Rust domain contract."""
    binding = require_rust_binding("provider_usage_validate_observation")
    validated = binding(dict(observation), now)
    if not isinstance(validated, dict):
        return dict(validated)
    return validated


def _status_observation(
    context: UsageProbeContext,
    *,
    now: float,
    outcome: UsageCollectionOutcome,
    reason_code: UsageReasonCode | None = None,
    diagnostic: str | None = None,
    source: UsageSource = "probe",
) -> dict[str, Any]:
    """Build a windowless observation that satisfies the domain inventory rules."""
    completeness: UsageCompleteness = "partial" if outcome == "error" else "complete"
    resolved_diagnostic = diagnostic
    if resolved_diagnostic is None:
        if reason_code is not None:
            resolved_diagnostic = _DIAGNOSTIC_BY_REASON.get(reason_code)
        elif outcome == "unsupported":
            resolved_diagnostic = _DIAGNOSTIC_BY_REASON["unsupported"]
    received_at = max(float(now), float(context.request_started_at))
    return {
        "schema_version": context.schema_version,
        "provider": context.provider,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": float(context.request_started_at),
        "received_at": received_at,
        "source": source,
        "outcome": outcome,
        "reason_code": reason_code,
        "diagnostic": resolved_diagnostic,
        "completeness": completeness,
        "authoritative_empty": False,
        "account_mode": None,
        "plan": None,
        "windows": [],
    }


def validated_status_observation(
    context: UsageProbeContext,
    *,
    now: float,
    outcome: UsageCollectionOutcome,
    reason_code: UsageReasonCode | None = None,
    diagnostic: str | None = None,
    source: UsageSource = "probe",
) -> dict[str, Any]:
    """Build and validate a windowless status observation."""
    return validate_observation(
        _status_observation(
            context,
            now=now,
            outcome=outcome,
            reason_code=reason_code,
            diagnostic=diagnostic,
            source=source,
        ),
        now=max(float(now), float(context.request_started_at)),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
