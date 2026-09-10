"""Locator builders for offline Fleet TUI fixtures."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def fleet_installation_id(hex_char: str = "a") -> str:
    """Return a stable fleet installation ID for tests."""
    return f"sase_inst_v1_{hex_char * 64}"


def fleet_logical_locator(
    *,
    installation_id: str | None = None,
    project_id: str = "sase-main",
    agent_id: str = "agent-1",
    family_id: str | None = "family-1",
) -> dict[str, Any]:
    """Build the logical-locator shape consumed by fleet projections."""
    origin_id = installation_id or fleet_installation_id()
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": origin_id,
            },
            "project_id": project_id,
        },
        "agent_id": agent_id,
        "family_id": family_id,
    }


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
