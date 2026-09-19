"""Fleet row summary builders for offline TUI fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.status_buckets import (
    PENDING_PLAN_REVIEW_STATUS_SET,
    status_bucket_for_values,
)
from tests.ace.tui._fleet_locator_fixture import (
    fleet_contract_schema_version,
    fleet_exact_key,
    fleet_exact_locator,
    fleet_installation_id,
    fleet_logical_key,
    fleet_logical_locator,
)

_OWNER_STATUS_GLYPHS = frozenset("√✓✔★")
_DISPLAY_BUCKET_TO_WIRE = {
    "Stopped": "stopped",
    "Failed": "failed",
    "Starting": "starting",
    "Running": "running",
    "Queued": "queued",
    "Waiting": "waiting",
    "Done": "done",
}


def fleet_summary(
    *,
    installation_id: str | None = None,
    project_id: str = "sase-main",
    project_name: str = "SASE",
    agent_id: str = "agent-1",
    run_id: str = "run-1",
    logical_key: str | None = None,
    exact_key: str | None = None,
    status: str = "running",
    revision: int = 1,
    patch_name: str = "remote-dispatch",
    agent_name: str | None = None,
    model: str = "gpt-5",
    provider: str = "codex",
    bounded_intent: str = "exercise fleet projection",
    needs_attention: bool = False,
    family_id: str | None = "family-1",
    freshness: str = "fresh",
    connection_health: str = "online",
    observed_at_unix: float = 1_800_000_000.0,
    occupied_runner_slot: bool | None = None,
    queue_weight: float | None = None,
    queue_weight_explicit: bool = False,
    queue_weight_invalid: bool = False,
    queue_weight_error: str | None = None,
    queue_capacity: int | None = None,
    queue_capacity_explicit: bool = False,
    row_kind: str = "agent_shell",
    family_role: str = "root",
    parent_timestamp: str | None = None,
    current_instance: bool | None = None,
    container_projected_concrete_agent: bool = False,
    project_label: str | None = None,
    started_at_unix: float | None = None,
    run_started_at_unix: float | None = None,
    stopped_at_unix: float | None = None,
    workspace_num: int | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    clan_tribe: str | None = None,
    tribe: str | None = None,
    status_bucket: str | None = None,
) -> dict[str, Any]:
    """Build one valid resolved remote row summary."""
    del patch_name  # Remote summaries expose project labels, not Patch labels.
    origin_id = installation_id or fleet_installation_id()
    logical = fleet_logical_locator(
        installation_id=origin_id,
        project_id=project_id,
        agent_id=agent_id,
        family_id=family_id,
    )
    exact = fleet_exact_locator(logical, agent_id=agent_id, run_id=run_id)
    logical_key = logical_key or fleet_logical_key(logical)
    exact_key = exact_key or fleet_exact_key(exact)
    row_revision = {
        "schema_version": 1,
        "logical_key": logical_key,
        "revision": revision,
    }
    display_status = _display_status(status)
    bucket = _status_bucket(status, explicit=status_bucket)
    lifecycle = _lifecycle_for_status(status)
    liveness = _liveness_for_status(status)
    observed_at_unix = _coherent_observed_at(
        observed_at_unix,
        started_at_unix,
        run_started_at_unix,
        stopped_at_unix,
    )
    derived_current_instance = liveness == "alive"
    if current_instance is None:
        current_instance = derived_current_instance
    if occupied_runner_slot is None:
        occupied_runner_slot = current_instance and bucket in {
            "running",
            "starting",
            "waiting",
            "queued",
        }
    summary: dict[str, Any] = {
        "schema_version": 1,
        "logical_locator": logical,
        "exact_locator": exact,
        "logical_key": logical_key,
        "exact_key": exact_key,
        "row_kind": row_kind,
        "family_role": family_role,
        "labels": {
            "schema_version": 1,
            "project_label": project_label
            if project_label is not None
            else project_name,
            "agent_label": agent_name or agent_id,
            "family_label": family_id,
            "owner_label": "bryan",
            "alias": None,
        },
        "project_name": project_name,
        "model": model,
        "provider": provider,
        "status": display_status,
        "status_bucket": bucket,
        "intent": bounded_intent,
        "observed_at_unix": observed_at_unix,
        "row_revision": row_revision,
        "lifecycle": lifecycle,
        "liveness": liveness,
        "connection_health": _connection_health(connection_health),
        "freshness": _freshness(freshness),
        "capabilities": {
            "schema_version": fleet_contract_schema_version(),
            "resource": ["content.read", "stop"],
            "host": [],
            "protocol": ["fleet.v1"],
        },
        "content": {
            "schema_version": 1,
            "handle_count": 1,
            "total_byte_len": len(bounded_intent),
            "kinds": ["transcript"],
            "supports_range": True,
            "supports_growth": current_instance,
        },
        "current_instance": current_instance,
        "dismissable": not current_instance,
        "needs_attention": needs_attention,
        "occupied_runner_slot": bool(occupied_runner_slot),
        "container_projected_concrete_agent": container_projected_concrete_agent,
    }
    if parent_timestamp is not None:
        summary["parent_timestamp"] = parent_timestamp
    if started_at_unix is not None:
        summary["started_at_unix"] = started_at_unix
    if run_started_at_unix is not None:
        summary["run_started_at_unix"] = run_started_at_unix
    if stopped_at_unix is not None:
        summary["stopped_at_unix"] = stopped_at_unix
    if workspace_num is not None:
        summary["workspace_num"] = workspace_num
    if agent_clan is not None:
        summary["agent_clan"] = agent_clan
    if agent_clan_generation is not None:
        summary["agent_clan_generation"] = agent_clan_generation
    if clan_tribe is not None:
        summary["clan_tribe"] = clan_tribe
    if tribe is not None:
        summary["tribe"] = tribe
    if queue_weight is not None:
        summary["queue_weight"] = queue_weight
    if queue_weight_explicit:
        summary["queue_weight_explicit"] = True
    if queue_weight_invalid:
        summary["queue_weight_invalid"] = True
    if queue_weight_error is not None:
        summary["queue_weight_error"] = queue_weight_error
    if queue_capacity is not None:
        summary["queue_capacity"] = queue_capacity
    if queue_capacity_explicit:
        summary["queue_capacity_explicit"] = True
    return summary


def _status_bucket(status: str, *, explicit: str | None = None) -> str:
    if explicit is not None:
        return explicit.casefold().replace("-", "_").replace(" ", "_")
    display = _canonical_owner_status(status)
    return _DISPLAY_BUCKET_TO_WIRE[status_bucket_for_values(display)]


def _lifecycle_for_status(status: str) -> str:
    display = _canonical_owner_status(status)
    if display.startswith("FAILED") or display == "ERROR":
        return "failed"
    if display in PENDING_PLAN_REVIEW_STATUS_SET or display == "QUESTION":
        return "asking"
    bucket = status_bucket_for_values(display)
    if bucket == "Failed":
        return "failed"
    if bucket == "Done":
        return "terminal"
    if bucket == "Starting":
        return "starting"
    if bucket in {"Waiting", "Queued"} or display in {
        "WAITING INPUT",
        "NEEDS INPUT",
        "BLOCKED",
    }:
        return "waiting"
    return "running"


def _liveness_for_status(status: str) -> str:
    lifecycle = _lifecycle_for_status(status)
    if lifecycle in {"starting", "running", "waiting", "asking"}:
        return "alive"
    return "dead"


def _display_status(status: str) -> str:
    original = status.strip()
    glyphs = ""
    body = original
    while body and (body[-1] in _OWNER_STATUS_GLYPHS or body[-1].isspace()):
        if body[-1] in _OWNER_STATUS_GLYPHS:
            glyphs = body[-1] + glyphs
        body = body[:-1]
    body = " ".join(body.replace("-", " ").replace("_", " ").split()).upper()
    return f"{body} {glyphs}".strip() if glyphs else body


def _canonical_owner_status(status: str) -> str:
    return _display_status(status).rstrip("".join(_OWNER_STATUS_GLYPHS) + " ").strip()


def _coherent_observed_at(*timestamps: float | None) -> float:
    values = [
        float(value)
        for value in timestamps
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return max(values) if values else 1_800_000_000.0


def _freshness(value: str) -> str:
    normalized = value.casefold().strip()
    if normalized in {"fresh", "aging", "stale", "unknown"}:
        return normalized
    if normalized.startswith("cached"):
        return "stale"
    return "unknown"


def _connection_health(value: str) -> str:
    normalized = value.casefold().strip()
    if normalized in {"online", "degraded", "offline", "unknown"}:
        return normalized
    if normalized in {"reconnecting", "reconnect", "slow"}:
        return "degraded"
    return "unknown"
