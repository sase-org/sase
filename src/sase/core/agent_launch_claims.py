"""Rust-backed RUNNING-field claim planning for agent launch."""

from __future__ import annotations

from typing import Any

from sase.core.agent_launch_wire import (
    WorkspaceClaimRequestWire,
    agent_launch_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding
from sase.running_field._model import WorkspaceClaim


def list_workspace_claims_from_content(content: str) -> list[WorkspaceClaim]:
    """Parse RUNNING workspace claims from project-file content via Rust."""

    binding = require_rust_binding("list_workspace_claims_from_content")
    rows: list[dict[str, Any]] = binding(content)
    return [
        WorkspaceClaim(
            workspace_num=int(row["workspace_num"]),
            workflow=str(row["workflow"]),
            cl_name=row.get("cl_name"),
            pid=int(row["pid"]),
            artifacts_timestamp=row.get("artifacts_timestamp"),
            pinned=bool(row.get("pinned", False)),
        )
        for row in rows
    ]


def plan_claim_workspace_from_content(
    content: str,
    request: WorkspaceClaimRequestWire,
) -> dict[str, Any]:
    """Return planned content for adding one RUNNING workspace claim."""

    binding = require_rust_binding("plan_claim_workspace_from_content")
    return dict(binding(content, agent_launch_wire_to_json_dict(request)))


def plan_transfer_workspace_claim_from_content(
    content: str,
    request: WorkspaceClaimRequestWire,
) -> dict[str, Any]:
    """Return planned content for transferring one RUNNING claim to a new PID."""

    binding = require_rust_binding("plan_transfer_workspace_claim_from_content")
    return dict(binding(content, agent_launch_wire_to_json_dict(request)))


def allocate_and_claim_workspace_from_content(
    content: str,
    min_workspace: int,
    max_workspace: int,
    request: WorkspaceClaimRequestWire,
) -> dict[str, Any]:
    """Return planned content for first-free allocation plus RUNNING claim."""

    binding = require_rust_binding("allocate_and_claim_workspace_from_content")
    return dict(
        binding(
            content,
            min_workspace,
            max_workspace,
            agent_launch_wire_to_json_dict(request),
        )
    )


def decide_workspace_occupant_conflict(
    occupant: dict[str, Any] | None,
    caller: dict[str, Any],
    occupant_pid_alive: bool,
    running_claim: dict[str, Any] | None,
    running_claim_pid_alive: bool,
) -> dict[str, Any]:
    """Decide whether a destructive workspace prep may proceed via Rust.

    ``occupant`` and ``running_claim`` are the wire-dict shapes of
    ``OccupantRecordWire`` / ``WorkspaceClaimWire`` (or ``None`` when
    absent); ``caller`` is an ``OccupancyCallerWire`` dict. Liveness of the
    occupant's and running claim's pids is computed by the caller.
    """

    binding = require_rust_binding("decide_workspace_occupant_conflict")
    return dict(
        binding(
            occupant,
            caller,
            occupant_pid_alive,
            running_claim,
            running_claim_pid_alive,
        )
    )
