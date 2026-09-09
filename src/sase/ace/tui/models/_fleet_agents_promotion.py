"""Singleton-to-family follow promotion derivation for fleet agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding
from sase.dispatch.follow_store import FollowStoreSnapshot

from ._fleet_agents_payload import host_payloads, summary_payloads
from ._fleet_agents_scalars import mapping, optional_str


def followed_batch_family_promotions(
    snapshot: FollowStoreSnapshot | None,
    followed_response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Derive safe singleton-to-family follow promotions from hydrated rows."""
    if (
        snapshot is None
        or followed_response is None
        or followed_response.get("disabled")
    ):
        return ()

    records = [
        record
        for record in (_follow_record_wire(item) for item in snapshot.active_records)
        if record is not None
    ]
    observations = _observation_locators(followed_response)
    if not records or not observations:
        return ()
    try:
        result = require_rust_binding("fleet_followed_batch_family_promotions")(
            {
                "schema_version": 1,
                "records": records,
                "observations": observations,
            }
        )
    except ValueError:
        return ()
    promotions = result.get("promotions") if isinstance(result, Mapping) else None
    if not isinstance(promotions, list):
        return ()
    return tuple(item for item in promotions if isinstance(item, dict))


def _observation_locators(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    locators: list[dict[str, Any]] = []
    seen: set[str] = set()
    for host in host_payloads(response):
        for summary in summary_payloads(host):
            locator = _locator_wire(mapping(summary.get("logical_locator")))
            if locator is None:
                continue
            key = (
                locator["project"]["origin"]["installation_id"],
                locator["project"]["project_id"],
                locator["agent_id"],
                locator.get("family_id") or "",
            )
            encoded = "|".join(key)
            if encoded in seen:
                continue
            seen.add(encoded)
            locators.append(locator)
    return locators


def _follow_record_wire(record: Mapping[str, Any]) -> dict[str, Any] | None:
    locator = _locator_wire(mapping(record.get("logical_locator")))
    created_by = optional_str(record.get("created_by"))
    state = optional_str(record.get("state"))
    created_at = record.get("created_at_unix")
    updated_at = record.get("updated_at_unix")
    if (
        locator is None
        or created_by not in {"explicit", "dispatch"}
        or state not in {"pending", "active"}
        or not isinstance(created_at, (int, float))
        or isinstance(created_at, bool)
        or not isinstance(updated_at, (int, float))
        or isinstance(updated_at, bool)
    ):
        return None
    try:
        logical_key = str(require_rust_binding("fleet_logical_locator_key")(locator))
    except (TypeError, ValueError):
        return None
    activated = record.get("activated_at_unix")
    if isinstance(activated, bool) or (
        activated is not None and not isinstance(activated, (int, float))
    ):
        activated = None
    operation_key = record.get("operation_key")
    if operation_key is not None and not isinstance(operation_key, Mapping):
        operation_key = None
    return {
        "schema_version": 1,
        "logical_locator": locator,
        "logical_key": logical_key,
        "created_by": created_by,
        "state": state,
        "created_at_unix": float(created_at),
        "updated_at_unix": float(updated_at),
        "activated_at_unix": None if activated is None else float(activated),
        "operation_key": None if operation_key is None else dict(operation_key),
    }


def _locator_wire(locator: Mapping[str, Any]) -> dict[str, Any] | None:
    project = mapping(locator.get("project"))
    origin = mapping(project.get("origin"))
    installation_id = optional_str(
        origin.get("installation_id"),
        locator.get("origin_installation_id"),
        locator.get("installation_id"),
    )
    project_id = optional_str(project.get("project_id"), locator.get("project_id"))
    agent_id = optional_str(locator.get("agent_id"))
    if installation_id is None or project_id is None or agent_id is None:
        return None
    family_id = optional_str(locator.get("family_id"))
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": installation_id,
            },
            "project_id": project_id,
        },
        "agent_id": agent_id,
        "family_id": family_id,
    }
