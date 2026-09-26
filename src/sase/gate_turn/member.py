"""Create the gate-turn member's artifacts directory."""

from __future__ import annotations

from typing import Any

from sase.notification_gates.model_turn import GateTurnSpec
from sase.turns.member import create_agent_session_turn_member

_GATE_INHERITED_METADATA_FIELDS = (
    "agent_clan",
    "agent_clan_generation",
    "queue_weight",
    "queue_weight_explicit",
    "runner_claim_owner_key",
)


def create_gate_turn_member(
    project_name: str,
    base_meta: dict[str, Any],
    *,
    lane: str,
    suffix: str,
    prev_artifacts_timestamp: str,
    workspace_num: int | None,
    gate_id: str,
    gate_kind: str,
    label: str,
    reason: str,
    creator_agent: str | None,
    timeout_seconds: float,
    request_fingerprint: str | None,
    turn: GateTurnSpec,
) -> str:
    """Create a pending gate-turn agent-session member."""
    next_output = ",".join(turn.next.output)
    gate_metadata: dict[str, Any] = {
        "gate_id": gate_id,
        "gate_kind": gate_kind,
        "gate_state": "pending",
        "gate_start_status": turn.pending_status,
        "gate_stop_status": turn.settled_status,
        "gate_accent": turn.accent,
        "gate_label": label,
        "gate_reason": reason,
        "gate_creator_agent": creator_agent,
        "gate_timeout_seconds": timeout_seconds,
        "gate_request_fingerprint": request_fingerprint,
        "gate_workspace_policy": turn.workspace,
        "gate_next_fork": turn.next.fork,
        "gate_next_output": next_output,
        "gate_next_raw_prompt": turn.next.raw_prompt,
        "proc_id": None,
        "pid": None,
    }
    if turn.next.prompt:
        gate_metadata["gate_next_action"] = turn.next.prompt
    if turn.next.model:
        gate_metadata["gate_next_model"] = turn.next.model
    if turn.next.suffix:
        gate_metadata["gate_next_suffix"] = turn.next.suffix
    if turn.next.role:
        gate_metadata["gate_next_role"] = turn.next.role

    return create_agent_session_turn_member(
        project_name,
        base_meta,
        agent_session=lane,
        suffix=suffix,
        prev_artifacts_timestamp=prev_artifacts_timestamp,
        workspace_num=workspace_num,
        turn_kind="gate",
        agent_session_role="gate",
        metadata=gate_metadata,
        inherited_metadata_fields=_GATE_INHERITED_METADATA_FIELDS,
    )


__all__ = ["create_gate_turn_member"]
