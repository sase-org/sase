"""Fleet row summary builders for offline TUI fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tests.ace.tui._fleet_locator_fixture import (
    fleet_exact_key,
    fleet_exact_locator,
    fleet_installation_id,
    fleet_logical_key,
    fleet_logical_locator,
)


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
    bucket = _status_bucket(status)
    lifecycle = _lifecycle_for_status(status)
    liveness = _liveness_for_status(status)
    current_instance = liveness == "alive"
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
        "row_kind": "agent_shell",
        "family_role": "root",
        "labels": {
            "schema_version": 1,
            "project_label": project_name,
            "agent_label": agent_name or agent_id,
            "family_label": family_id,
            "owner_label": "bryan",
            "alias": None,
        },
        "project_name": project_name,
        "model": model,
        "provider": provider,
        "status": _display_status(status),
        "status_bucket": bucket,
        "intent": bounded_intent,
        "observed_at_unix": observed_at_unix,
        "row_revision": row_revision,
        "lifecycle": lifecycle,
        "liveness": liveness,
        "connection_health": _connection_health(connection_health),
        "freshness": _freshness(freshness),
        "capabilities": {
            "schema_version": 1,
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
        "container_projected_concrete_agent": False,
    }
    if queue_weight is not None:
        summary["queue_weight"] = queue_weight
    if queue_weight_explicit:
        summary["queue_weight_explicit"] = True
    if queue_weight_invalid:
        summary["queue_weight_invalid"] = True
    if queue_weight_error is not None:
        summary["queue_weight_error"] = queue_weight_error
    return summary


def _status_bucket(status: str) -> str:
    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"done", "complete", "completed", "terminal"}:
        return "done"
    if normalized in {"stopped", "cancelled", "canceled"}:
        return "stopped"
    if normalized == "starting":
        return "starting"
    if normalized in {"queued", "pending"}:
        return "queued"
    if normalized in {"waiting", "waiting_input", "needs_input", "blocked"}:
        return "stopped"
    if normalized in {"asking", "question"}:
        return "stopped"
    return "running"


def _lifecycle_for_status(status: str) -> str:
    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"done", "complete", "completed", "terminal"}:
        return "terminal"
    if normalized in {"stopped", "cancelled", "canceled"}:
        return "terminal"
    if normalized == "starting":
        return "starting"
    if normalized in {"waiting", "waiting_input", "needs_input", "blocked", "queued"}:
        return "waiting"
    if normalized in {"asking", "question"}:
        return "asking"
    return "running"


def _liveness_for_status(status: str) -> str:
    lifecycle = _lifecycle_for_status(status)
    if lifecycle in {"starting", "running", "waiting", "asking"}:
        return "alive"
    return "dead"


def _display_status(status: str) -> str:
    return status.replace("-", " ").replace("_", " ").upper()


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
