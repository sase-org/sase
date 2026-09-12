"""Wire records for Rust-backed failure retryability classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RETRYABILITY_WIRE_SCHEMA_VERSION = 1

RETRYABILITY_VERDICT_TRANSIENT = "retryable_transient"
RETRYABILITY_VERDICT_AFTER_DELAY = "retryable_after_delay"
RETRYABILITY_VERDICT_PERMANENT = "permanent"

RETRY_OPERATION_GIT = "git"
RETRY_OPERATION_GIT_CLONE = "git_clone"
RETRY_OPERATION_GH = "gh"


@dataclass(frozen=True)
class RetryabilityVerdictWire:
    """Deterministic retryability verdict returned by ``sase_core_rs``."""

    schema_version: int
    verdict: str
    reason: str
    retryable: bool
    retry_after_seconds: int | None


def retryability_verdict_from_dict(
    data: dict[str, Any],
) -> RetryabilityVerdictWire:
    """Rehydrate a retryability verdict from the PyO3 dict shape."""
    schema_version = int(data["schema_version"])
    if schema_version != RETRYABILITY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs retryability wire is stale: "
            f"expected schema {RETRYABILITY_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version}"
        )
    retry_after = data.get("retry_after_seconds")
    return RetryabilityVerdictWire(
        schema_version=schema_version,
        verdict=str(data["verdict"]),
        reason=str(data["reason"]),
        retryable=bool(data["retryable"]),
        retry_after_seconds=None if retry_after is None else int(retry_after),
    )


__all__ = [
    "RETRYABILITY_VERDICT_AFTER_DELAY",
    "RETRYABILITY_VERDICT_PERMANENT",
    "RETRYABILITY_VERDICT_TRANSIENT",
    "RETRYABILITY_WIRE_SCHEMA_VERSION",
    "RETRY_OPERATION_GH",
    "RETRY_OPERATION_GIT",
    "RETRY_OPERATION_GIT_CLONE",
    "RetryabilityVerdictWire",
    "retryability_verdict_from_dict",
]
