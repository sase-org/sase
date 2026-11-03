"""Kind-specific staged-handoff adopters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sase.agent.staged_handoff import StagedHandoffError, read_staged_successor
from sase.axe._run_agent_exec_staged_shared import (
    StagedAdopter,
    StagedAdoptionOutcome,
    StagedInlineContinuation,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext


def _is_current_in_process_member(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
) -> bool:
    """Return whether *run_metadata* names the runner's current member.

    Pipe, plan-coder, and question successors continue inside the same runner
    through ``continue_as_successor``: ``ctx.agent_name`` stays the session
    base while ``state.current_role_suffix`` and ``state.current_artifacts_dir``
    move to the member. A later staged handoff then persists that member
    identity, which must adopt without a kill-based fallback.
    """
    from sase.plan_chain import (
        agent_session_value,
        canonical_plan_chain_suffix,
        plan_chain_agent_name,
    )

    ctx = continuation.ctx
    state = continuation.state
    persisted_name = run_metadata.get("name")
    base = ctx.agent_name
    suffix = getattr(state, "current_role_suffix", None)
    if not isinstance(persisted_name, str) or not persisted_name:
        return False
    if not isinstance(base, str) or not base:
        return False
    if not isinstance(suffix, str) or not suffix:
        return False
    if canonical_plan_chain_suffix(suffix) is None:
        return False
    try:
        expected = plan_chain_agent_name(base, suffix)
    except ValueError:
        return False
    if persisted_name != expected:
        return False
    try:
        session_value = agent_session_value(run_metadata)
    except Exception:  # noqa: BLE001 - malformed metadata is not a member.
        return False
    return session_value == base


def _runner_ctx_for_in_process_member(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
) -> AgentExecContext:
    """Rebind per-member facts while keeping the session-base runner identity."""
    from dataclasses import replace

    ctx = continuation.ctx
    return replace(
        ctx,
        agent_model=run_metadata.get("model", ctx.agent_model),
        agent_llm_provider=run_metadata.get("llm_provider", ctx.agent_llm_provider),
        agent_vcs_provider=run_metadata.get("vcs_provider", ctx.agent_vcs_provider),
        agent_meta=dict(run_metadata),
    )


def _runner_ctx_from_metadata(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
) -> AgentExecContext:
    """Rebind the live runner context to persisted agent identity."""
    if _is_current_in_process_member(continuation, run_metadata):
        return _runner_ctx_for_in_process_member(continuation, run_metadata)
    ctx = continuation.ctx
    persisted_name = run_metadata.get("name")
    if isinstance(persisted_name, str) and persisted_name != ctx.agent_name:
        raise StagedHandoffError(
            "persisted agent identity differs from the active runner identity"
        )
    return _runner_ctx_with_metadata(continuation, run_metadata, persisted_name)


def _runner_ctx_from_approval_context(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
    approval_context: Mapping[str, Any],
) -> AgentExecContext:
    """Bind approval continuations to the persisted origin execution facts."""
    from dataclasses import replace

    execution = approval_context.get("execution")
    if not isinstance(execution, Mapping):
        raise StagedHandoffError("staged approval execution context is malformed")
    ctx = _runner_ctx_from_metadata(continuation, run_metadata)
    text_fields = (
        "cl_name",
        "project_file",
        "workspace_dir",
        "output_path",
        "timestamp",
        "update_target",
        "project_name",
        "artifacts_dir",
        "artifacts_timestamp",
        "vcs_tag",
        "agent_name",
        "agent_model",
        "agent_llm_provider",
        "agent_vcs_provider",
        "multi_agent_prompt_file",
        "workflow_name",
    )
    values = {
        key: execution[key]
        for key in text_fields
        if isinstance(execution.get(key), str)
    }
    if type(execution.get("workspace_num")) is int:
        values["workspace_num"] = execution["workspace_num"]
    if isinstance(execution.get("is_home_mode"), bool):
        values["is_home_mode"] = execution["is_home_mode"]
    if isinstance(execution.get("agent_hidden"), bool):
        values["agent_hidden"] = execution["agent_hidden"]
    if _is_current_in_process_member(continuation, run_metadata):
        persisted_name = run_metadata.get("name")
        if values.get("agent_name") == persisted_name:
            base_name = continuation.ctx.agent_name
            if isinstance(base_name, str) and base_name:
                values["agent_name"] = base_name
    return replace(ctx, **values, agent_meta=dict(run_metadata))


def _runner_ctx_from_monitor_metadata(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
) -> AgentExecContext:
    """Accept the root promotion and the current in-process member."""
    if _is_current_in_process_member(continuation, run_metadata):
        return _runner_ctx_for_in_process_member(continuation, run_metadata)
    from sase.core.agent_identity_facade import normalize_owned_agent_name
    from sase.agent._agent_session_promotion import (
        is_exact_agent_session_root_promotion,
    )

    ctx = continuation.ctx
    persisted_name = run_metadata.get("name")
    if not isinstance(persisted_name, str) or not persisted_name:
        raise StagedHandoffError("persisted monitor starter identity is missing")
    if persisted_name == ctx.agent_name:
        return _runner_ctx_from_metadata(continuation, run_metadata)

    active_meta_name = ctx.agent_meta.get("name")
    expected_base = (
        normalize_owned_agent_name(ctx.agent_name) if ctx.agent_name else None
    )
    valid_promotion = (
        isinstance(active_meta_name, str)
        and active_meta_name == ctx.agent_name
        and expected_base is not None
        and is_exact_agent_session_root_promotion(
            persisted_name, expected_base, run_metadata
        )
    )
    if not valid_promotion:
        raise StagedHandoffError(
            "persisted agent identity differs from the active runner identity"
        )
    return _runner_ctx_with_metadata(continuation, run_metadata, persisted_name)


def _runner_ctx_with_metadata(
    continuation: StagedInlineContinuation,
    run_metadata: Mapping[str, Any],
    persisted_name: Any,
) -> AgentExecContext:
    ctx = continuation.ctx
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

    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged plan record has no staged_id")
    origin = continuation.state.current_artifacts_dir
    approval_context = staged_record.get("approval_context")
    if not isinstance(approval_context, Mapping):
        raise StagedHandoffError("staged plan approval context is missing")
    outcome = handle_staged_plan_marker(
        {**dict(payload), "plan_file": plan_file},
        _runner_ctx_from_approval_context(continuation, run_metadata, approval_context),
        continuation.state,
        planner_response=response,
        staged_id=staged_id,
        approval_context=approval_context,
    )
    successor = read_staged_successor(origin, staged_id=staged_id)
    if successor is None:
        return outcome
    child = successor["successor"]
    return StagedAdoptionOutcome(
        outcome=outcome,
        custodian=str(child["artifacts_dir"]),
        refs={
            "successor_artifacts_dir": child["artifacts_dir"],
            "successor_launch_identity": child["launch_identity"],
            "successor_prompt_ref": child["prompt_ref"],
        },
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
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged questions record has no staged_id")
    approval_context = staged_record.get("approval_context")
    if not isinstance(approval_context, Mapping):
        raise StagedHandoffError("staged question approval context is missing")

    origin = continuation.state.current_artifacts_dir
    from sase.axe.run_agent_exec_questions import handle_staged_questions_marker

    outcome = handle_staged_questions_marker(
        dict(payload),
        _runner_ctx_from_approval_context(continuation, run_metadata, approval_context),
        continuation.state,
        provider_response=response,
        staged_id=staged_id,
        approval_context=approval_context,
    )
    custodian = continuation.state.current_artifacts_dir
    if custodian == origin:
        gate = continuation.state.question_gate_artifacts_dir
        if isinstance(gate, str) and gate.strip():
            custodian = gate
    refs: dict[str, Any] = {}
    staged_id = staged_record.get("staged_id")
    if isinstance(staged_id, str):
        successor = read_staged_successor(origin, staged_id=staged_id)
        if successor is not None:
            child = successor["successor"]
            custodian = str(child["artifacts_dir"])
            refs = {
                "successor_artifacts_dir": child["artifacts_dir"],
                "successor_launch_identity": child["launch_identity"],
                "successor_prompt_ref": child["prompt_ref"],
            }
    return StagedAdoptionOutcome(outcome=outcome, custodian=custodian, refs=refs)


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

    origin = continuation.state.current_artifacts_dir
    outcome = handle_staged_pipe_marker(
        dict(payload),
        _runner_ctx_from_metadata(continuation, run_metadata),
        continuation.state,
        provider_response=response,
        staged_id=str(staged_record.get("staged_id") or ""),
    )
    successor = read_staged_successor(
        origin,
        staged_id=str(staged_record.get("staged_id") or ""),
    )
    if successor is None:
        raise StagedHandoffError("pipe adopter did not persist a successor identity")
    return StagedAdoptionOutcome(
        outcome=outcome,
        custodian=continuation.state.current_artifacts_dir,
        refs={
            "successor_launch_identity": successor["successor"]["launch_identity"],
            "successor_prompt_ref": successor["successor"]["prompt_ref"],
        },
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
    monitor_ctx = _runner_ctx_from_monitor_metadata(continuation, run_metadata)
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
    from sase.axe.run_agent_exec_monitor import capture_monitor_handoff

    continuation_result = capture_monitor_handoff(
        {
            "monitor_id": monitor_id,
            "member_artifacts_dir": member_dir,
        },
        monitor_ctx,
        continuation.state,
        response=response,
        status="completed",
        promotion_base_name=continuation.ctx.agent_name,
    )
    if continuation_result is None:
        raise StagedHandoffError(
            "starter continuation delta was not persisted before monitor launch"
        )
    from sase.monitor.start_stage import launch_from_persisted_payload

    record = launch_from_persisted_payload(
        member_dir,
        starter_continuation_node_id=continuation_result.node_id,
    )
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
