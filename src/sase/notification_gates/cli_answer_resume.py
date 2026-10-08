"""``--resume`` for an already-answered gate.

When a prior attempt persisted ``response.json`` but its side effects (a
successor launch, a bead action) failed, resuming reruns only those side
effects and settles the gate turn, instead of re-executing the answered
branch.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.gate_turn.settlement import settle_gate_turn
from sase.gate_turn.store import find_gate_turn_by_gate_id
from sase.notification_gates._cli_answer_shared import answered_payload
from sase.notification_gates.cli_support import (
    GateCliError,
    ResolvedGateCliBundle,
)
from sase.notification_gates.decision import read_current_receipt, receipt_acceptance_id
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.failure_notifications import (
    dismiss_gate_execution_failed,
)
from sase.notification_gates.failure_outcome import with_follow_up_stage_tracking
from sase.notification_gates.journal import current_post_response_failure


def resume_answered_shell(
    bundle: ResolvedGateCliBundle,
    *,
    selected_ids: list[str],
    input_data: object | None,
    option_inputs: Mapping[str, object] | None,
    feedback: str | None,
    source: str,
    expected_review_revision: int | None = None,
) -> dict[str, Any]:
    """Resume an unfinished coder handoff using the persisted answer."""
    existing = read_json_object(bundle.response_path)
    raw_ids = existing.get("selected_option_ids")
    stored_ids = [str(item) for item in raw_ids] if isinstance(raw_ids, list) else []
    if stored_ids != selected_ids:
        raise GateCliError(
            "answered-gate --resume must repeat the stored options "
            f"{', '.join(stored_ids) or '(none)'}; got {', '.join(selected_ids)}"
        )
    stored_feedback = existing.get("feedback")
    if feedback is not None and stored_feedback not in (None, feedback):
        raise GateCliError(
            "answered-gate --resume feedback does not match the stored answer"
        )
    stored_inputs = existing.get("option_inputs")
    if option_inputs is not None and stored_inputs not in (None, dict(option_inputs)):
        raise GateCliError(
            "answered-gate --resume option inputs do not match the stored answer"
        )
    if input_data is not None and existing.get("input") not in (None, input_data):
        raise GateCliError(
            "answered-gate --resume --input does not match the stored answer"
        )
    receipt = read_current_receipt(bundle.root)
    if (
        current_post_response_failure(bundle.root, receipt, stage="side_effects")
        is not None
    ):
        # A prior attempt persisted response.json but its side effects (a
        # successor launch, a bead action) failed -- rerun only those,
        # skipping any launch response.json already recorded, before
        # settling the shell so the handoff resumes against a launch that
        # actually happened.
        from sase.plan_gate_decisions import recover_plan_stamp_from_response

        recover_plan_stamp_from_response(bundle.root)
        execution = execute_gate_selection(
            bundle.root,
            selected_ids,
            input_data,
            feedback=feedback,
            source=source,
            retry="resume",
            option_inputs=option_inputs,
            expected_review_revision=expected_review_revision,
        )
        existing = execution.response
        receipt = read_current_receipt(bundle.root)
    gate_turn = find_gate_turn_by_gate_id(None, bundle.request_id)
    if gate_turn is None:
        raise GateCliError(
            "answered-gate --resume requires the original gate-turn member"
        )
    settled = with_follow_up_stage_tracking(
        bundle.root,
        acceptance_id=receipt_acceptance_id(receipt),
        source=source,
        run=lambda: settle_gate_turn(
            gate_turn,
            gate_state="answered",
            reason="gate answered",
            resume=True,
        ),
    )
    dismiss_gate_execution_failed(bundle_path=bundle.root, envelope=bundle.envelope)
    payload = answered_payload(bundle, existing, True)
    payload["followup_agent"] = settled.followup_agent
    payload["followup_outcome"] = settled.followup_outcome
    payload["followup_error"] = settled.followup_error
    payload["handoff_resumed"] = True
    if settled.followup_agent and settled.followup_outcome in {
        "launched",
        "launched-degraded",
    }:
        payload["message"] = f"Gate handoff already complete: {settled.followup_agent}"
    return payload


__all__ = ["resume_answered_shell"]
