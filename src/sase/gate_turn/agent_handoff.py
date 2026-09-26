"""Handing a creator agent to the gate turn it just created."""

from __future__ import annotations

import os

from sase.agent.gate_intent import clear_gate_intent
from sase.agent.pending_handoff import GATE_PENDING_MARKER
from sase.gate_turn.models import GateTurnError, GateTurnRecord
from sase.gate_turn.settlement import settle_gate_turn
from sase.gate_turn.start_claim import restore_gate_turn_claim
from sase.gate_turn.transaction import GateTurnCreation
from sase.notification_gates.executor import cancel_gate
from sase.turns.handoff import (
    TurnHandoffError,
    maybe_handoff_turn_from_agent,
    will_handoff_turn_to_agent_runner,
)


def will_handoff_gate_to_agent_runner() -> bool:
    """Return whether ``maybe_handoff_gate_from_agent`` will kill this runner.

    ``kill_agent_runner_group()`` is ``NoReturn``, so any output a caller
    wants to show (a creation descriptor, JSON envelope, or summary) must be
    emitted *before* calling ``maybe_handoff_gate_from_agent`` -- not after,
    and not conditioned on its return value, which the process never lives to
    observe when this is true.
    """
    return will_handoff_turn_to_agent_runner(os.environ)


def maybe_handoff_gate_from_agent(
    creation: GateTurnCreation | GateTurnRecord,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Write the in-agent gate handoff marker and kill this runner."""
    record = creation.record if isinstance(creation, GateTurnCreation) else creation
    if record.is_terminal:
        clear_gate_intent(artifacts_dir)
        return False
    try:
        return maybe_handoff_turn_from_agent(
            marker_name=GATE_PENDING_MARKER,
            marker_data=_gate_pending_payload(record),
            artifacts_dir=artifacts_dir,
            env=os.environ,
            on_marker_written=lambda: clear_gate_intent(artifacts_dir),
            member="gate turn",
        )
    except TurnHandoffError as exc:
        clear_gate_intent(artifacts_dir)
        if isinstance(creation, GateTurnCreation):
            _compensate_failed_handoff(creation, str(exc))
        raise GateTurnError(str(exc)) from exc


def _compensate_failed_handoff(creation: GateTurnCreation, error: str) -> None:
    try:
        cancel_gate(
            creation.gate.bundle_path,
            reason="handoff_failed",
            source="gate_turn",
        )
    except Exception:
        pass
    if creation.project_file is not None and creation.claim_move is not None:
        restore_gate_turn_claim(
            creation.project_file,
            move=creation.claim_move,
            cl_name=creation.cl_name,
        )
    settle_gate_turn(
        creation.record,
        gate_state="stopped",
        reason=f"handoff marker failed: {error}",
        creator_live=True,
    )


def _gate_pending_payload(record: GateTurnRecord) -> dict[str, str]:
    return {
        "gate_id": record.gate_id,
        "member_artifacts_dir": record.artifacts_dir,
        "member_agent_name": record.member_agent_name,
        "kind": record.kind,
    }


__all__ = [
    "GATE_PENDING_MARKER",
    "maybe_handoff_gate_from_agent",
    "will_handoff_gate_to_agent_runner",
]
