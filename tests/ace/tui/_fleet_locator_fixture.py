"""Locator builders for offline Fleet TUI fixtures."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def fleet_installation_id(hex_char: str = "a") -> str:
    """Return a stable fleet installation ID for tests."""
    return f"sase_inst_v1_{hex_char * 64}"


def fleet_contract_schema_version() -> int:
    """Return the core's current fleet-contract schema version.

    A host's bare ``installation_id`` is re-derived by the core into an
    ``OriginLocatorWire`` stamped with this version, then compared for
    equality against the origin embedded in each raw summary fixture. A
    hardcoded literal here would go stale every time the core's schema
    version advances and the two origins would stop matching.
    """
    return require_rust_binding("fleet_contract_schema_version")()


def fleet_logical_locator(
    *,
    installation_id: str | None = None,
    project_id: str = "sase-main",
    agent_id: str = "agent-1",
    legacy_family_id: str | None = "family-1",
    agent_session_id: str | None = None,
) -> dict[str, Any]:
    """Build the logical-locator shape consumed by fleet projections.

    Legacy wire fixture: core still emits ``family_id`` until core-contract,
    so the default shape carries the legacy key. Pass ``agent_session_id``
    for the new shape instead (the core accepts it as the ``family_id``
    replacement, never alongside it); new-shape keys are read first by the
    fleet projection models.
    """
    origin_id = installation_id or fleet_installation_id()
    locator: dict[str, Any] = {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": fleet_contract_schema_version(),
                "installation_id": origin_id,
            },
            "project_id": project_id,
        },
        "agent_id": agent_id,
    }
    if agent_session_id is not None:
        locator["agent_session_id"] = agent_session_id
    else:
        # legacy agent-family spelling: core emits "family_id" until core-contract.
        locator["family_id"] = legacy_family_id
    return locator


def fleet_logical_key(locator: Mapping[str, Any]) -> str:
    """Return the core logical key corresponding to a locator."""
    return str(require_rust_binding("fleet_logical_locator_key")(dict(locator)))


def fleet_exact_locator(
    logical: Mapping[str, Any],
    *,
    agent_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Build the exact instance-locator shape consumed by fleet projections."""
    return {
        "schema_version": 1,
        "logical": copy.deepcopy(dict(logical)),
        "shell_id": f"shell-{agent_id}",
        "run_id": run_id,
        "attempt_id": "attempt-1",
    }


def fleet_exact_key(locator: Mapping[str, Any]) -> str:
    """Return the core exact key corresponding to an instance locator."""
    return str(require_rust_binding("fleet_instance_locator_key")(dict(locator)))
