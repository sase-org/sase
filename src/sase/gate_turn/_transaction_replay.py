"""Replay preconditions for resuming a partially published gate turn."""

from __future__ import annotations

import os

from sase.gate_turn._transaction_creator import CreatorContext
from sase.gate_turn.models import GateTurnError, GateTurnRecord
from sase.notification_gates.model_request import GateSpec


def validate_replay_identity(
    spec: GateSpec, creator: CreatorContext, replay: GateTurnRecord
) -> None:
    """Refuse a replay whose member identity does not match this request."""
    request_id = spec.request_id or replay.gate_id
    if replay.kind and replay.kind != spec.kind:
        raise GateTurnError(
            f"request id {request_id} already belongs to a {replay.kind} gate, "
            f"not {spec.kind}"
        )
    turn = spec.turn
    if (
        turn is not None
        and replay.workspace_policy
        and replay.workspace_policy != turn.workspace
    ):
        raise GateTurnError(
            f"request id {request_id} was published with workspace policy "
            f"{replay.workspace_policy!r}, not {turn.workspace!r}"
        )
    recorded_creator = replay.creator_agent
    expected_creator = (
        creator.meta.get("name")
        if isinstance(creator.meta.get("name"), str) and creator.meta.get("name")
        else creator.target_name
    )
    if recorded_creator and expected_creator and recorded_creator != expected_creator:
        raise GateTurnError(
            f"request id {request_id} was created by {recorded_creator}, "
            f"not {expected_creator}"
        )


def replay_claim_already_applied(
    creator: CreatorContext, replay: GateTurnRecord, workspace_policy: str
) -> bool:
    """Return whether inherit/release claim work already landed for *replay*."""
    if creator.workspace_num is None or creator.workspace_num == 0:
        return True
    if creator.runner_pid is None:
        return True
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(creator.project_file)
    member_timestamp = replay.timestamp or os.path.basename(
        replay.artifacts_dir.rstrip("/")
    )
    held = False
    for claim in claims:
        if claim.workspace_num != creator.workspace_num:
            continue
        held = True
        if (
            workspace_policy == "inherit"
            and claim.artifacts_timestamp == member_timestamp
        ):
            return True
    if workspace_policy == "release":
        return not held
    return False
