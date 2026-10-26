"""Rust-backed policy facade for sidecar publication retry decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

SIDECAR_PUBLICATION_WIRE_SCHEMA_VERSION = 1

SIDECAR_PUBLICATION_ACTION_SUCCESS = "success"
SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY = "integrate_and_retry"
SIDECAR_PUBLICATION_ACTION_STOP = "stop"


@dataclass(frozen=True)
class _SidecarPublicationDecision:
    schema_version: int
    action: str
    classification: str
    reason: str
    attempt: int
    max_attempts: int
    retryable: bool


@dataclass(frozen=True)
class _SidecarPublicationRejection:
    schema_version: int
    classification: str
    commit_ids: tuple[str, ...]
    relative_paths: tuple[str, ...]


def decide_sidecar_publication_after_push(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    attempt: int,
) -> _SidecarPublicationDecision:
    """Classify one ``git push`` result through ``sase_core_rs``."""
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    binding = require_rust_binding("decide_sidecar_publication_after_push")
    raw = binding(returncode, stdout, stderr, attempt)
    return _decision_from_dict(raw)


def classify_sidecar_publication_push_result(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
) -> _SidecarPublicationRejection:
    """Return the sanitized structured classification of one remote push result."""
    binding = require_rust_binding("classify_sidecar_publication_push_result")
    raw = binding(returncode, stdout, stderr)
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict sidecar rejection")
    try:
        result = _SidecarPublicationRejection(
            schema_version=_require_int(raw, "schema_version"),
            classification=_require_str(raw, "classification"),
            commit_ids=_require_str_tuple(raw, "commit_ids"),
            relative_paths=_require_str_tuple(raw, "relative_paths"),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"sase_core_rs returned an incomplete sidecar rejection: missing {exc}"
        ) from exc
    if result.schema_version != SIDECAR_PUBLICATION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs sidecar publication rejection wire is stale: "
            f"{result.schema_version}"
        )
    if result.classification not in {
        "success",
        "rejected_secret_scan",
        "rejected_repository_rule",
        "rejected_non_fast_forward",
        "rejected_fetch_first",
        "unknown_failure",
    }:
        raise RuntimeError(
            "sase_core_rs returned an unknown sidecar rejection classification"
        )
    return result


def _decision_from_dict(raw: Any) -> _SidecarPublicationDecision:
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict sidecar decision")
    try:
        decision = _SidecarPublicationDecision(
            schema_version=_require_int(raw, "schema_version"),
            action=_require_str(raw, "action"),
            classification=_require_str(raw, "classification"),
            reason=_require_str(raw, "reason"),
            attempt=_require_int(raw, "attempt"),
            max_attempts=_require_int(raw, "max_attempts"),
            retryable=_require_bool(raw, "retryable"),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"sase_core_rs returned an incomplete sidecar decision: missing {exc}"
        ) from exc
    if decision.schema_version != SIDECAR_PUBLICATION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs sidecar publication wire is stale: {decision.schema_version}"
        )
    if decision.action not in {
        SIDECAR_PUBLICATION_ACTION_SUCCESS,
        SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY,
        SIDECAR_PUBLICATION_ACTION_STOP,
    }:
        raise RuntimeError(
            f"sase_core_rs returned an unknown sidecar action: {decision.action}"
        )
    return decision


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise RuntimeError(f"sase_core_rs sidecar decision field {key!r} is not str")
    return value


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int):
        raise RuntimeError(f"sase_core_rs sidecar decision field {key!r} is not int")
    return value


def _require_bool(raw: dict[str, Any], key: str) -> bool:
    value = raw[key]
    if not isinstance(value, bool):
        raise RuntimeError(f"sase_core_rs sidecar decision field {key!r} is not bool")
    return value


def _require_str_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw[key]
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise RuntimeError(f"sase_core_rs sidecar rejection field {key!r} is not str[]")
    return tuple(value)


__all__ = [
    "SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY",
    "SIDECAR_PUBLICATION_ACTION_STOP",
    "SIDECAR_PUBLICATION_ACTION_SUCCESS",
    "SIDECAR_PUBLICATION_WIRE_SCHEMA_VERSION",
    "classify_sidecar_publication_push_result",
    "decide_sidecar_publication_after_push",
]
