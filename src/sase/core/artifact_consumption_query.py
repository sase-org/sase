"""Rust-backed queries for the artifact-consumption ledger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.core.artifact_consumption import default_artifact_consumption_log_path
from sase.core.rust import require_rust_binding


ARTIFACT_CONSUMPTION_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArtifactConsumptionSummary:
    """Aggregated consumption for one canonical artifact reference."""

    consumption_count: int
    distinct_agent_count: int
    agent_names: tuple[str, ...]
    roles: tuple[str, ...]
    first_consumed_at: str | None
    last_consumed_at: str | None

    def to_json_dict(self) -> dict[str, object]:
        """Return the stable JSON representation used by artifact show."""

        return {
            "consumption_count": self.consumption_count,
            "distinct_agent_count": self.distinct_agent_count,
            "agent_names": list(self.agent_names),
            "roles": list(self.roles),
            "first_consumed_at": self.first_consumed_at,
            "last_consumed_at": self.last_consumed_at,
        }


def summarize_artifact_consumption(
    refs: Sequence[str] | None = None,
    *,
    log_path: Path | str | None = None,
) -> dict[str, ArtifactConsumptionSummary]:
    """Summarize ledger events, optionally restricted to canonical refs."""

    _require_consumption_schema()
    resolved_log = (
        Path(default_artifact_consumption_log_path() if log_path is None else log_path)
        .expanduser()
        .resolve(strict=False)
    )
    binding = require_rust_binding("artifact_consumption_summary")
    raw_summaries = binding(
        str(resolved_log),
        None if refs is None else [str(reference) for reference in refs],
    )
    if not isinstance(raw_summaries, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-consumption summary: "
            "expected an object"
        )

    summaries: dict[str, ArtifactConsumptionSummary] = {}
    for reference, raw_summary in cast(Mapping[object, object], raw_summaries).items():
        if not isinstance(reference, str) or not reference:
            raise RuntimeError(
                "sase_core_rs returned an incompatible artifact-consumption "
                "summary key: expected a non-empty string"
            )
        summaries[reference] = _summary_from_wire(raw_summary, reference=reference)
    return summaries


def _require_consumption_schema() -> None:
    binding = require_rust_binding("artifact_consumption_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_CONSUMPTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-consumption wire is stale: "
            f"expected {ARTIFACT_CONSUMPTION_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _summary_from_wire(
    raw: object,
    *,
    reference: str,
) -> ArtifactConsumptionSummary:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-consumption summary "
            f"for {reference!r}: expected an object"
        )
    summary = cast(Mapping[str, Any], raw)
    consumption_count = _nonnegative_int(
        summary.get("consumption_count"),
        reference=reference,
        field="consumption_count",
    )
    distinct_agent_count = _nonnegative_int(
        summary.get("distinct_agent_count"),
        reference=reference,
        field="distinct_agent_count",
    )
    agent_names = _string_tuple(
        summary.get("agent_names"),
        reference=reference,
        field="agent_names",
    )
    roles = _string_tuple(
        summary.get("roles"),
        reference=reference,
        field="roles",
    )
    first_consumed_at = _optional_string(
        summary.get("first_consumed_at"),
        reference=reference,
        field="first_consumed_at",
    )
    last_consumed_at = _optional_string(
        summary.get("last_consumed_at"),
        reference=reference,
        field="last_consumed_at",
    )
    return ArtifactConsumptionSummary(
        consumption_count=consumption_count,
        distinct_agent_count=distinct_agent_count,
        agent_names=agent_names,
        roles=roles,
        first_consumed_at=first_consumed_at,
        last_consumed_at=last_consumed_at,
    )


def _nonnegative_int(value: object, *, reference: str, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-consumption summary "
            f"for {reference!r}: {field} must be a non-negative integer"
        )
    return value


def _string_tuple(value: object, *, reference: str, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-consumption summary "
            f"for {reference!r}: {field} must be a list of non-empty strings"
        )
    return tuple(value)


def _optional_string(value: object, *, reference: str, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-consumption summary "
            f"for {reference!r}: {field} must be a string or null"
        )
    return value


__all__ = [
    "ARTIFACT_CONSUMPTION_WIRE_SCHEMA_VERSION",
    "ArtifactConsumptionSummary",
    "summarize_artifact_consumption",
]
