"""Report-specific display fields for the Agents runner-capacity view."""

from __future__ import annotations

import time
from pathlib import PurePath
from typing import Any

from ._agent_runner_slot_types import RunnerCapacityHolder
from .agent import Agent


def report_capacity_snapshot_fields(
    raw_snapshot: dict[str, Any],
    report: Any | None,
    source_agents: dict[str, Agent],
    occupied_capacity: float | None,
    fallback_holders: tuple[RunnerCapacityHolder, ...],
) -> dict[str, Any]:
    """Return report metadata shared by estimate and authoritative snapshots."""
    claims = raw_snapshot.get("claims", ())
    report_available = bool(getattr(report, "accounting_available", False))
    return {
        "holders": (
            _accounting_capacity_holders(report, source_agents)
            if report is not None and report_available
            else fallback_holders
        ),
        "source": "authoritative" if report is not None else "estimate",
        "report_age_seconds": (
            max(0.0, time.time() - float(report.computed_at))
            if report is not None
            else None
        ),
        "accounting_valid": (
            bool(report.accounting_valid) if report is not None else None
        ),
        "accounting_available": (report_available if report is not None else None),
        "known_occupied_capacity": occupied_capacity,
        "over_limit": bool(report.over_limit) if report is not None else None,
        "scan_current": bool(report.scan_current) if report is not None else None,
        "claim_owner_keys": _claim_owner_keys(claims),
        "claim_artifact_dirs": _claim_artifact_dirs(claims),
        "limit_provenance": getattr(report, "limit", None)
        if report is not None
        else None,
        "occupied_capacity": (
            occupied_capacity
            if report is None or bool(report.accounting_valid)
            else None
        ),
    }


def _accounting_capacity_holders(
    report: Any,
    source_agents: dict[str, Agent],
) -> tuple[RunnerCapacityHolder, ...]:
    """Build holder labels from the report's per-record accounting rows."""
    record_inputs = {
        item.artifact_dir: item
        for item in getattr(report, "record_inputs", ())
        if isinstance(getattr(item, "artifact_dir", None), str)
    }
    holders: list[RunnerCapacityHolder] = []
    for entry in getattr(report, "accounting", ()):
        if not isinstance(entry, dict) or entry.get("state") != "holding":
            continue
        artifact_dir = _text_value(entry.get("artifact_dir"))
        agent = source_agents.get(artifact_dir) if artifact_dir is not None else None
        label = _text_value(entry.get("agent_name"))
        if label is None and agent is not None:
            label = agent.presented_agent_name or agent.agent_name or agent.cl_name
        if label is None and artifact_dir is not None:
            label = PurePath(artifact_dir).name
        if label is None:
            continue
        weight = _finite_float(entry.get("charged_weight"))
        input_record = record_inputs.get(artifact_dir or "")
        kind = None
        if getattr(input_record, "turn_kind", None) == "monitor" or (
            agent is not None and agent.is_monitor
        ):
            kind = "monitor"
        elif agent is not None and agent.is_gate:
            kind = "gate"
        holders.append(
            RunnerCapacityHolder(
                label=label,
                weight=0.0 if weight is None else weight,
                kind=kind,
                claim_owner_key=_text_value(entry.get("claim_owner_key")),
            )
        )
    holders.sort(key=lambda holder: (-holder.weight, holder.label))
    return tuple(holders)


def _claim_owner_keys(claims: object) -> tuple[str, ...]:
    if not isinstance(claims, list | tuple):
        return ()
    return tuple(
        sorted(
            {
                owner_key
                for claim in claims
                if isinstance(claim, dict)
                and (owner_key := _text_value(claim.get("owner_key"))) is not None
            }
        )
    )


def _claim_artifact_dirs(claims: object) -> tuple[str, ...]:
    if not isinstance(claims, list | tuple):
        return ()
    artifact_dirs: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        owner_dir = _text_value(claim.get("owner_artifact_dir"))
        if owner_dir is not None:
            artifact_dirs.add(owner_dir)
        dirs = claim.get("artifact_dirs")
        if isinstance(dirs, list | tuple):
            artifact_dirs.update(item for item in dirs if isinstance(item, str))
    return tuple(sorted(artifact_dirs))


def _text_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    return result if result == result and abs(result) != float("inf") else None


__all__ = ["report_capacity_snapshot_fields"]
