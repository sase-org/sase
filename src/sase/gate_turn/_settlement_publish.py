"""Publish a gate-turn terminal state without launching follow-up."""

from __future__ import annotations

import time
from typing import Any

from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.gate_turn._settlement_support import (
    apply_branch_policy,
    bundle_documents,
    done_marker,
    is_terminal_meta,
    project_name_from_artifacts_dir,
    read_meta,
    write_decision_record,
    write_meta,
    write_settlement_chat,
)
from sase.gate_turn.followup_policy import (
    resolve_gate_branch_presentation,
    resolve_gate_followup,
    shell_block_unparseable,
)
from sase.gate_turn.handoff import with_gate_followup_lock
from sase.gate_turn.handoff_launch import record_selected_options
from sase.gate_turn.models import GateTurnRecord, GateTurnState
from sase.gate_turn.start_claim import hold_gate_turn_claim_for_settlement
from sase.turns.settlement import (
    finalize_turn_workflow_state,
    touch_turn_refresh_pulse,
)


def publish_gate_turn_terminal_state(
    record: GateTurnRecord,
    *,
    gate_state: GateTurnState = "answered",
    reason: str | None = None,
) -> GateTurnRecord:
    """Publish decision record, index, and refresh pulse without follow-up.

    Post-terminal epic launch and coder handoff run after this so observers
    see ``response.json`` and the shell's terminal state first.
    """
    artifacts_dir = record.artifacts_dir
    with with_gate_followup_lock(artifacts_dir):
        meta = read_meta(artifacts_dir)
        if is_terminal_meta(meta):
            touch_turn_refresh_pulse(project_name_from_artifacts_dir(artifacts_dir))
            return record
        return _publish_gate_turn_terminal_locked(
            record,
            meta,
            gate_state=gate_state,
            reason=reason,
        )


def _publish_gate_turn_terminal_locked(
    record: GateTurnRecord,
    meta: dict[str, Any],
    *,
    gate_state: GateTurnState,
    reason: str | None,
) -> GateTurnRecord:
    artifacts_dir = record.artifacts_dir
    envelope, response, cancellation = bundle_documents(meta)
    record_selected_options(meta, response)
    policy = resolve_gate_followup(envelope, gate_state=gate_state, response=response)
    status, accent = resolve_gate_branch_presentation(
        envelope, gate_state=gate_state, response=response
    )
    apply_branch_policy(
        meta,
        policy=policy,
        status=status,
        accent=accent,
        shell_unparseable=shell_block_unparseable(envelope),
    )
    meta["gate_state"] = "settling"
    write_meta(artifacts_dir, meta)

    decision_path, decision_text = write_decision_record(
        artifacts_dir,
        meta,
        gate_state=gate_state,
        reason=reason,
        envelope=envelope,
        response=response,
        cancellation=cancellation,
    )
    meta["gate_decision_path"] = str(decision_path)
    meta["chat_path"] = write_settlement_chat(artifacts_dir, meta, decision_text)
    write_meta(artifacts_dir, meta)

    project_name = project_name_from_artifacts_dir(artifacts_dir)
    if project_name:
        from sase.workflows.utils import get_project_file_path

        hold_gate_turn_claim_for_settlement(
            get_project_file_path(project_name),
            meta,
            artifacts_dir=artifacts_dir,
            update_meta_field=update_meta_field,
        )

    marker = done_marker(meta, gate_state=gate_state, reason=reason)
    write_done_marker_and_update_index(artifacts_dir, marker)
    finalize_turn_workflow_state(artifacts_dir)

    meta = read_meta(artifacts_dir)
    meta["gate_state"] = gate_state
    meta["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_meta(artifacts_dir, meta)
    touch_turn_refresh_pulse(project_name)
    from sase.gate_turn.store import read_gate_turn_marker

    return (
        read_gate_turn_marker(project_name or record.project_name, artifacts_dir)
        or record
    )
