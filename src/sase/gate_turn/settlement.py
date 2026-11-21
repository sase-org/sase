"""Gate-turn claim, follow-up, and terminal marker settlement."""

from __future__ import annotations

import time
from typing import Any

from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.gate_turn._settlement_publish import publish_gate_turn_terminal_state
from sase.gate_turn._settlement_support import (
    apply_branch_policy,
    bundle_documents,
    done_marker,
    gate_decision_title,
    is_terminal_meta,
    project_name_from_artifacts_dir,
    read_meta,
    write_decision_record,
    write_meta,
    write_settlement_chat,
)
from sase.gate_turn.followup_policy import (
    GateFollowupPolicy,
    resolve_gate_branch_presentation,
    resolve_gate_followup,
    shell_block_unparseable,
)
from sase.gate_turn.handoff import (
    CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS,
    FOLLOWUP_LOCK_TIMEOUT_SECONDS,
    merge_followup_fields,
    with_gate_followup_lock,
)
from sase.gate_turn.handoff_launch import (
    launch_or_record_followup,
    record_selected_options,
    settle_already_terminal_handoff,
    suppress_live_creator_followup,
)
from sase.gate_turn.models import GateTurnRecord, GateTurnState
from sase.gate_turn.start_claim import hold_gate_turn_claim_for_settlement
from sase.turns.settlement import (
    TurnSettlementConfig,
    finalize_turn_workflow_state,
    touch_turn_refresh_pulse,
)

GATE_FOLLOWUP_DEGRADED_OUTCOME = "launched-degraded"
LOST_FOLLOWUP_ERROR = "follow-up not launched because the gate turn was marked lost"

_GATE_SETTLEMENT_CONFIG = TurnSettlementConfig(
    next_action_field="gate_next_action",
    agent_field="gate_followup_agent",
    outcome_field="gate_followup_outcome",
    error_field="gate_followup_error",
    degraded_reason_field="gate_followup_degraded_reason",
    prompt_path_field="gate_followup_prompt_path",
    lost_state="lost",
    stopped_state="stopped",
    lost_followup_error=LOST_FOLLOWUP_ERROR,
    degraded_outcome=GATE_FOLLOWUP_DEGRADED_OUTCOME,
    fallback_followup_error="gate follow-up launch failed",
    missing_project_error=(
        "could not resolve the gate turn's project from its artifacts path"
    ),
)


def settle_gate_turn(
    record: GateTurnRecord,
    *,
    gate_state: GateTurnState,
    reason: str | None = None,
    creator_live: bool = False,
    wait_out_contention: bool = False,
    resume: bool = False,
) -> GateTurnRecord:
    """Settle a gate-turn member into ``gate_state``.

    Never launches a follow-up, releases a claim, or notifies until the shell
    itself is terminal and its artifact index is visible -- otherwise a
    forked successor could resolve ``#fork`` before this shell's own
    decision record and chat exist.

    ``creator_live=True`` marks a settlement that runs inside the still-live
    creator's own process (the ``%auto`` short-circuit, or after a failed
    handoff): no follow-up is launched and no claim is disposed of, because
    the creator itself still owns the lane and the workspace. A policy that
    would otherwise have launched is stashed as an artifact instead, so
    nothing the shell's author declared is silently lost.

    ``resume=True`` recovers an already-answered shell whose requested coder
    handoff never completed. Approval and archive receipts stay as they are.

    ``wait_out_contention=True`` is for callers settling after the answer is
    durable and selected commands may already have produced side effects. It
    gives another legitimate settler time to finish its follow-up launch.
    """
    artifacts_dir = record.artifacts_dir
    timeout = (
        CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS
        if creator_live or wait_out_contention
        else FOLLOWUP_LOCK_TIMEOUT_SECONDS
    )
    with with_gate_followup_lock(artifacts_dir, timeout=timeout):
        settled = _settle_gate_turn_locked(
            record,
            gate_state=gate_state,
            reason=reason,
            creator_live=creator_live,
            resume=resume,
        )
    try:
        from sase.gate_turn.execution_failure import clear_gate_execution_failure

        clear_gate_execution_failure(artifacts_dir)
    except Exception:
        pass
    return settled


def _settle_gate_turn_locked(
    record: GateTurnRecord,
    *,
    gate_state: GateTurnState,
    reason: str | None,
    creator_live: bool,
    resume: bool,
) -> GateTurnRecord:
    artifacts_dir = record.artifacts_dir
    meta = read_meta(artifacts_dir)
    already_settled = is_terminal_meta(meta)
    if already_settled:
        envelope, response, _cancellation = bundle_documents(meta)
        record_selected_options(meta, response)
        policy = resolve_gate_followup(
            envelope,
            gate_state=gate_state,
            response=response,
        )
        project_name = project_name_from_artifacts_dir(artifacts_dir)
        if creator_live:
            suppress_live_creator_followup(
                artifacts_dir,
                meta,
                policy=policy,
                gate_state=gate_state,
                envelope=envelope,
                response=response,
                reason=reason,
            )
            write_meta(artifacts_dir, meta)
            touch_turn_refresh_pulse(project_name)
            from sase.gate_turn.store import read_gate_turn_marker

            return (
                read_gate_turn_marker(
                    project_name or record.project_name, artifacts_dir
                )
                or record
            )
        return settle_already_terminal_handoff(
            record,
            meta,
            envelope=envelope,
            response=response,
            policy=policy,
            reason=reason,
            resume=resume,
            config=_GATE_SETTLEMENT_CONFIG,
            done_marker=done_marker(
                meta,
                gate_state=gate_state,
                reason=reason,
            ),
        )

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
    if project_name and not creator_live:
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

    if creator_live:
        suppress_live_creator_followup(
            artifacts_dir,
            meta,
            policy=policy,
            gate_state=gate_state,
            envelope=envelope,
            response=response,
            reason=reason,
        )
    else:
        latched = _apply_gate_hijack_latch(
            record,
            meta,
            gate_state=gate_state,
            policy=policy,
            envelope=envelope,
            response=response,
            reason=reason,
        )
        if not latched:
            launch_or_record_followup(
                artifacts_dir,
                meta,
                gate_state=gate_state,
                project_name=project_name,
                policy=policy,
                envelope=envelope,
                response=response,
                reason=reason,
                already_settled=False,
                resume=False,
                config=_GATE_SETTLEMENT_CONFIG,
            )
    disk = read_meta(artifacts_dir)
    merge_followup_fields(meta, disk)
    write_meta(artifacts_dir, meta)

    marker = done_marker(meta, gate_state=gate_state, reason=reason)
    write_done_marker_and_update_index(artifacts_dir, marker)

    from sase.gate_turn.store import read_gate_turn_marker

    return (
        read_gate_turn_marker(project_name or record.project_name, artifacts_dir)
        or record
    )


def _apply_gate_hijack_latch(
    record: GateTurnRecord,
    meta: dict[str, Any],
    *,
    gate_state: GateTurnState,
    policy: GateFollowupPolicy | None,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None,
) -> bool:
    """Apply a pending hijack after the gate decision, before its hand-off.

    The saved response and decision record remain authoritative. A latch only
    suppresses the follow-up launch and records its persisted prompt for
    recovery to continue later.
    """
    from sase.agent.hijack import ledger
    from sase.agent.hijack.facts import resolve_hijack_subject
    from sase.agent.hijack.latch import apply_latch_at_boundary
    from sase.agent.hijack._stop_claim import remove_intent
    from sase.gate_turn.followup import (
        GATE_FOLLOWUP_PERSISTENCE,
        build_suppressed_gate_followup_prompt,
    )
    from sase.turns.followup import persist_followup_prompt

    subject = resolve_hijack_subject(record.member_agent_name)
    target = subject.target
    if target is None:
        return False
    target_key = ledger.target_key_for(
        None if target.is_home else target.project_file,
        target.agent_session or target.name,
    )
    if not target_key:
        return False
    active = ledger.find_active_record_by_target_key(target_key)
    if active is None or active.get("state") != "latched":
        return False

    prompt_path: str | None = None
    if policy is not None:
        prompt = build_suppressed_gate_followup_prompt(
            record.artifacts_dir,
            meta,
            gate_state=gate_state,
            policy=policy,
            envelope=envelope,
            response=response,
            reason=reason,
        )
        prompt_path = persist_followup_prompt(
            record.artifacts_dir, prompt, GATE_FOLLOWUP_PERSISTENCE
        )

    if policy is not None:
        meta["gate_followup_outcome"] = "suppressed"
        if prompt_path:
            meta["gate_followup_prompt_path"] = prompt_path
        update_meta_field(record.artifacts_dir, "gate_followup_outcome", "suppressed")
        if prompt_path:
            update_meta_field(
                record.artifacts_dir, "gate_followup_prompt_path", prompt_path
            )

    outcome = apply_latch_at_boundary(
        target_key,
        "gate",
        gate_state,
        target=target,
        suppressed_followup=(
            {"kind": "gate_followup", "ref": prompt_path}
            if policy is not None and prompt_path
            else None
        ),
    )
    if outcome.get("verdict") == "applied":
        remove_intent(target.artifacts_dir)
        return True
    # Once a durable latch exists, uncertainty must retain custody. Letting the
    # ordinary hand-off path run here could launch the very successor the user
    # asked us to hold.
    return True


__all__ = [
    "GATE_FOLLOWUP_DEGRADED_OUTCOME",
    "LOST_FOLLOWUP_ERROR",
    "gate_decision_title",
    "project_name_from_artifacts_dir",
    "publish_gate_turn_terminal_state",
    "settle_gate_turn",
]
