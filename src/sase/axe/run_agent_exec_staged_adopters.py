"""Kind-specific staged-handoff adopters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sase.agent.staged_handoff import StagedHandoffError
from sase.axe._run_agent_exec_staged_shared import (
    StagedAdopter,
    StagedAdoptionOutcome,
    StagedInlineContinuation,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext


def _runner_ctx_from_metadata(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
) -> AgentExecContext:
    """Rebind the live runner context to persisted agent identity."""
    ctx = continuation.ctx
    persisted_name = run_metadata.get("name")
    if isinstance(persisted_name, str) and persisted_name != ctx.agent_name:
        raise StagedHandoffError(
            "persisted agent identity differs from the active runner identity"
        )
    return replace(
        ctx,
        agent_name=persisted_name
        if isinstance(persisted_name, str)
        else ctx.agent_name,
        agent_model=run_metadata.get("model", ctx.agent_model),
        agent_llm_provider=run_metadata.get("llm_provider", ctx.agent_llm_provider),
        agent_vcs_provider=run_metadata.get("vcs_provider", ctx.agent_vcs_provider),
        agent_meta=dict(run_metadata),
    )


def _adopt_plan(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> str | None | StagedAdoptionOutcome:
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        raise StagedHandoffError("staged plan payload is malformed")
    plan_file = payload.get("plan_file")
    if not isinstance(plan_file, str) or not plan_file:
        raise StagedHandoffError("staged plan payload has no plan_file")

    from sase.axe.run_agent_exec_plan import handle_staged_plan_marker

    return handle_staged_plan_marker(
        {**dict(payload), "plan_file": plan_file},
        _runner_ctx_from_metadata(continuation, run_metadata),
        continuation.state,
        planner_response=response,
    )


def _adopt_questions(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> StagedAdoptionOutcome:
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        raise StagedHandoffError("staged questions payload is malformed")
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise StagedHandoffError("staged questions payload has no questions")

    origin = continuation.state.current_artifacts_dir
    from sase.axe.run_agent_exec_questions import handle_staged_questions_marker

    outcome = handle_staged_questions_marker(
        dict(payload),
        _runner_ctx_from_metadata(continuation, run_metadata),
        continuation.state,
        provider_response=response,
    )
    custodian = continuation.state.current_artifacts_dir
    if custodian == origin:
        gate = continuation.state.question_gate_artifacts_dir
        if isinstance(gate, str) and gate.strip():
            custodian = gate
    return StagedAdoptionOutcome(outcome=outcome, custodian=custodian)


def _adopt_pipe(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> StagedAdoptionOutcome:
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        raise StagedHandoffError("staged pipe payload is malformed")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise StagedHandoffError("staged pipe payload has no prompt")

    from sase.axe.run_agent_exec_pipe import handle_staged_pipe_marker

    outcome = handle_staged_pipe_marker(
        dict(payload),
        _runner_ctx_from_metadata(continuation, run_metadata),
        continuation.state,
        provider_response=response,
    )
    return StagedAdoptionOutcome(
        outcome=outcome,
        custodian=continuation.state.current_artifacts_dir,
    )


def _adopt_gate(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> StagedAdoptionOutcome:
    from sase.axe.run_agent_exec_staged_gate import handle_staged_gate_marker

    adopted = handle_staged_gate_marker(
        staged_record,
        _runner_ctx_from_metadata(continuation, run_metadata),
        continuation,
        provider_response=response,
    )
    refs: dict[str, Any] = {
        "gate_id": adopted.gate_id,
        "gate_request_id": adopted.request_id,
        "member_artifacts_dir": adopted.member_artifacts_dir,
    }
    if adopted.notification_id:
        refs["notification_id"] = adopted.notification_id
    return StagedAdoptionOutcome(
        outcome=adopted.outcome,
        custodian=adopted.member_artifacts_dir if adopted.retains_workspace else None,
        refs=refs,
    )


def _adopt_monitor(
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    response: str,
) -> StagedAdoptionOutcome:
    """Launch a staged monitor after finalizer settlement.

    ``response`` is the already-persisted real model reply; this path never
    writes it over with a synthetic monitor summary and never resets kill
    state. Workspace transfer and custody happen inside the staged launch.
    """
    del response
    _runner_ctx_from_metadata(continuation, run_metadata)
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        raise StagedHandoffError("staged monitor payload is malformed")
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged monitor record has no staged_id")
    monitor_id = payload.get("monitor_id")
    if not isinstance(monitor_id, str) or not monitor_id:
        raise StagedHandoffError("staged monitor payload has no monitor_id")
    from sase.monitor.staged_owner import read_staged_owner_index

    member_dir: str | None = None
    try:
        index = read_staged_owner_index(monitor_id)
    except Exception:  # noqa: BLE001 - missing index is a refusal, not a crash.
        index = None
    if isinstance(index, Mapping) and index.get("staged_id") == staged_id:
        candidate = index.get("artifacts_dir")
        if isinstance(candidate, str) and candidate.strip():
            member_dir = candidate.strip()
    if member_dir is None:
        raise StagedHandoffError(
            "staged monitor member is unknown for "
            f"monitor {monitor_id!r} stage {staged_id!r}"
        )
    from sase.monitor.start_stage import launch_from_persisted_payload

    record = launch_from_persisted_payload(member_dir)
    return StagedAdoptionOutcome(
        outcome="monitored",
        custodian=record.artifacts_dir,
        refs={
            "monitor_id": record.monitor_id,
            "member_artifacts_dir": record.artifacts_dir,
            "staged_id": staged_id,
        },
    )


STAGED_HANDOFF_ADOPTERS: dict[str, StagedAdopter] = {
    "plan": _adopt_plan,
    "pipe": _adopt_pipe,
    "questions": _adopt_questions,
    "gate": _adopt_gate,
    "monitor": _adopt_monitor,
}


__all__ = ["STAGED_HANDOFF_ADOPTERS"]
