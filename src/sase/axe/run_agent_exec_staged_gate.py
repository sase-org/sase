"""Adopt a staged ``kind: gate`` handoff after finalizer settlement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.agent.staged_handoff import StagedHandoffError
from sase.gate_turn.publisher import publish_staged_gate

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_staged import StagedInlineContinuation
    from sase.axe.run_agent_exec_types import AgentExecContext


@dataclass(frozen=True)
class _StagedGateAdoption:
    """Publication result the dispatcher turns into custody and receipt refs."""

    outcome: str
    member_artifacts_dir: str
    gate_id: str
    request_id: str
    notification_id: str | None
    retains_workspace: bool


def handle_staged_gate_marker(
    staged_record: Mapping[str, Any],
    ctx: AgentExecContext,
    continuation: StagedInlineContinuation,
    *,
    provider_response: str,
) -> _StagedGateAdoption:
    """Publish the staged gate, then adopt it without a synthetic chat summary.

    ``provider_response`` is the already-persisted real model reply; this
    path never writes it over with a gate summary.
    """
    del provider_response
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        raise StagedHandoffError("staged gate payload is malformed")
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged gate record has no staged_id")
    artifacts_dir = continuation.state.current_artifacts_dir
    if not artifacts_dir:
        raise StagedHandoffError("staged gate adoption has no artifacts directory")

    creation = publish_staged_gate(
        payload,
        staged_id=staged_id,
        artifacts_dir=artifacts_dir,
    )

    from sase.axe.run_agent_exec_gate import handle_gate_marker

    gate_data = {
        "gate_id": creation.record.gate_id,
        "member_artifacts_dir": creation.record.artifacts_dir,
        "member_agent_name": creation.record.member_agent_name,
        "kind": creation.record.kind,
    }
    outcome = handle_gate_marker(
        gate_data,
        ctx,
        continuation.state,
        persist_chat=False,
    )
    retains_workspace = (
        staged_record.get("successor_workspace") == "inherit"
        or creation.record.workspace_policy == "inherit"
    )
    notification_id = creation.gate.notification_id
    return _StagedGateAdoption(
        outcome=outcome,
        member_artifacts_dir=creation.record.artifacts_dir,
        gate_id=creation.record.gate_id,
        request_id=creation.gate.request_id or creation.record.gate_id,
        notification_id=notification_id if isinstance(notification_id, str) else None,
        retains_workspace=retains_workspace,
    )


__all__ = ["handle_staged_gate_marker"]
