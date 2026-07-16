"""Plan marker handling for the agent execution loop."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.run_agent_runtime import format_agent_run_runtime
from sase.agent_family import (
    FamilyStateSnapshot,
    HandoffEvent,
    build_handoff_event,
    evaluate_handoff_event,
    evaluate_plan_approval_transition,
    family_runtime_metadata_for_role,
    family_state_snapshot,
)
from sase.axe.run_agent_family_metadata import record_family_runtime_metadata
from sase.axe.run_agent_exec_plan_artifacts import (
    store_followup_prompt_artifact,
    write_plan_path_artifact,
)
from sase.axe.run_agent_helpers import (
    assemble_feedback_replan_prompt,
    create_followup_artifacts,
    finalize_handoff_artifacts_as_completed,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
    update_step_marker_chat_path,
)
from sase.axe.runner_signals import reset_killed, was_killed
from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    allocate_agent_family_child_suffix,
    plan_chain_agent_name,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

_store_followup_prompt_artifact = store_followup_prompt_artifact
_write_plan_path_artifact = write_plan_path_artifact


def _saved_chat_suffixes(state: LoopState) -> tuple[str, ...]:
    return tuple(suffix for suffix, _path in state.saved_chat_paths if suffix)


def _family_state_snapshot(
    state: LoopState,
    interrupted_role: str,
) -> FamilyStateSnapshot:
    return family_state_snapshot(
        current_role_suffix=state.current_role_suffix,
        feedback_bullets=state.feedback_bullets,
        qa_round_count=len(state.qa_rounds),
        saved_chat_suffixes=_saved_chat_suffixes(state),
        agent_family_role=interrupted_role,
    )


def _coerce_plan_event(
    plan_data: dict[str, Any] | HandoffEvent,
    state: LoopState,
) -> HandoffEvent:
    if isinstance(plan_data, HandoffEvent):
        return plan_data
    return build_handoff_event(
        kind="plan_submitted",
        artifacts_dir=state.current_artifacts_dir,
        payload=plan_data,
        current_role_suffix=state.current_role_suffix,
    )


def agent_name_for_suffix(ctx: AgentExecContext, suffix: str | None) -> str | None:
    if not ctx.agent_name or not suffix:
        return None
    return plan_chain_agent_name(ctx.agent_name, suffix)


def _state_reserved_suffixes(state: LoopState, *extra: str | None) -> tuple[str, ...]:
    suffixes = [suffix for suffix, _path in state.saved_chat_paths if suffix]
    if state.current_role_suffix:
        suffixes.append(state.current_role_suffix)
    suffixes.extend(suffix for suffix in extra if suffix)
    return tuple(suffixes)


def record_workflow_metadata(
    artifacts_dir: str,
    relationships: dict[str, Any],
) -> None:
    retained_fields = {
        "plan_submitted_at",
        "plan_path",
        "changespec_name",
        "feedback_submitted_at",
        "sdd_prompt_path",
        "sdd_plan_path",
        "plan_committed",
        "questions_submitted_at",
        "question_request_path",
        "question_response_path",
        "question_session_id",
        "agent_family_config_id",
        "agent_family_config_version",
        "agent_family_config_hash",
        "active_gate_id",
        "active_gate_renderer",
        "family_state",
    }
    for key, value in relationships.items():
        if key in retained_fields and value is not None and value != "":
            update_meta_field(artifacts_dir, key, value)


def handle_plan_marker(
    plan_data: dict[str, Any] | HandoffEvent,
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Handle a plan marker left by ``sase plan``.

    Returns a loop-outcome string to break the loop, or ``None`` to continue.
    """
    event = _coerce_plan_event(plan_data, state)
    normalize_handoff_interruption_state(state.current_artifacts_dir)
    finalize_handoff_artifacts_as_completed(state.current_artifacts_dir)
    evaluation = evaluate_handoff_event(
        event,
        _family_state_snapshot(state, event.interrupted_role),
    )
    record_family_runtime_metadata(
        state.current_artifacts_dir,
        evaluation.runtime_metadata.as_meta_fields(),
    )
    # Only set the planner suffix on the original workflow entry;
    # feedback round agents keep their numeric suffixes.
    if state.feedback_round == 0:
        update_meta_suffix(state.current_artifacts_dir, PLAN_CHAIN_PLAN_SUFFIX)

    plan_submitted_at_dt = datetime.now(UTC)
    plan_submitted_at = plan_submitted_at_dt.isoformat()
    run_started_at = ctx.agent_meta.get("run_started_at")
    if not isinstance(run_started_at, str) or not run_started_at:
        run_started_at = None
    agent_runtime = format_agent_run_runtime(
        launch_timestamp_suffix=ctx.artifacts_timestamp,
        run_started_at=run_started_at,
        completion_time=plan_submitted_at_dt,
    )
    record_workflow_metadata(
        state.current_artifacts_dir,
        {
            "plan_submitted_at": plan_submitted_at,
            "plan_path": event.payload.get("plan_file"),
            "changespec_name": ctx.cl_name,
        },
    )

    from sase.llm_provider._plan_utils import handle_plan_approval

    # Clear the killed flag set by the plan command's SIGTERM
    # so the poll loop only exits on a NEW kill signal.
    reset_killed()
    plan_result = handle_plan_approval(
        event.payload.get("plan_file"),
        str(uuid.uuid4()),
        killed_check=was_killed,
        agent_name=ctx.agent_name,
        agent_model=ctx.agent_model,
        agent_llm_provider=ctx.agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=ctx.vcs_tag,
    )
    if plan_result is None and was_killed():
        return "killed"
    if plan_result is None:
        return "plan_rejected"

    # Write plan_path.json so the TUI can show the plan
    # in the file panel for the .plan agent entry.
    _write_plan_path_artifact(state.current_artifacts_dir, plan_result.plan_file)
    record_workflow_metadata(
        state.current_artifacts_dir,
        {
            "plan_path": plan_result.plan_file,
            "changespec_name": ctx.cl_name,
        },
    )

    # Save a chat file for the planner step (the LLM response was lost
    # to SIGTERM, so we use a plan-file preview as the synthetic response).
    from sase.history.chat import save_chat_history
    from sase.history.chat_extras import format_extra_sections
    from sase.history.chat_links import format_plan_as_response

    plan_response = format_plan_as_response(plan_result.plan_file)
    _planner_suffix = state.current_role_suffix or PLAN_CHAIN_PLAN_SUFFIX
    planner_agent = agent_name_for_suffix(ctx, _planner_suffix)
    _planner_extra = format_extra_sections(state.current_artifacts_dir)
    _planner_chat = save_chat_history(
        prompt=state.current_prompt,
        response=plan_response,
        workflow="ace-run",
        agent=planner_agent,
        timestamp=ctx.timestamp,
        extra_sections=_planner_extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=planner_agent,
        metadata_model=ctx.agent_model,
        metadata_llm_provider=ctx.agent_llm_provider,
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
    )
    state.saved_chat_paths.append((_planner_suffix, _planner_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _planner_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _planner_chat)

    # Feedback: spawn a new agent with the original prompt +
    # accumulated "Additional Requirements" section.
    if plan_result.action == "feedback":
        assert plan_result.feedback is not None
        state.feedback_round += 1
        state.feedback_bullets.append(plan_result.feedback)
        transition = evaluate_plan_approval_transition(
            action=plan_result.action,
            commit_plan=plan_result.commit_plan,
            run_coder=plan_result.run_coder,
            feedback_count=len(state.feedback_bullets),
            qa_round_count=len(state.qa_rounds),
            saved_chat_suffixes=_saved_chat_suffixes(state),
        )

        feedback_submitted_at = datetime.now(UTC).isoformat()
        update_meta_field(
            state.current_artifacts_dir,
            "feedback_submitted_at",
            feedback_submitted_at,
        )

        suffix = (
            allocate_agent_family_child_suffix(
                ctx.agent_name,
                transition.suffix_template or f"{PLAN_CHAIN_PLAN_SUFFIX}-@",
                extra_reserved_suffixes=_state_reserved_suffixes(state),
            )
            if ctx.agent_name
            else f"{PLAN_CHAIN_PLAN_SUFFIX}-{state.feedback_round - 1}"
        )
        followup_family_metadata = family_runtime_metadata_for_role(
            transition.target_role or "feedback",
            role_suffix=suffix,
            feedback_count=len(state.feedback_bullets),
            qa_round_count=len(state.qa_rounds),
            saved_chat_suffixes=_saved_chat_suffixes(state),
        )
        feedback_agent_name = agent_name_for_suffix(ctx, suffix)
        record_workflow_metadata(
            state.current_artifacts_dir,
            {
                "feedback_submitted_at": feedback_submitted_at,
                "followup_agent_name": feedback_agent_name,
                "plan_path": plan_result.plan_file,
            },
        )
        record_family_runtime_metadata(
            state.current_artifacts_dir,
            followup_family_metadata.as_meta_fields(),
        )
        state.current_role_suffix = suffix
        state.agent_step += 1
        if state.agent_step == 2 and ctx.agent_name:
            promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
        state.current_artifacts_dir = create_followup_artifacts(
            ctx.project_name,
            ctx.agent_meta,
            state.current_role_suffix,
            convert_timestamp_to_artifacts_format(ctx.timestamp),
            workspace_num=ctx.workspace_num,
            agent_name_override=plan_chain_agent_name(
                ctx.agent_name,
                state.current_role_suffix,
            )
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
            relationships={
                "plan_path": plan_result.plan_file,
                "feedback_submitted_at": feedback_submitted_at,
                "changespec_name": ctx.cl_name,
                "source_plan_agent_name": planner_agent,
                **followup_family_metadata.as_followup_relationships(),
            },
        )

        # Reconstruct prompt: original + merged Q&A + requirements.
        state.current_prompt = assemble_feedback_replan_prompt(
            state.original_prompt,
            state.feedback_bullets,
            state.qa_rounds,
        )
        # A ``/sase_questions`` interruption from the replan phase rebuilds from
        # this feedback prompt rather than the bare planner prompt.
        state.question_base_prompt = state.current_prompt
        _store_followup_prompt_artifact(
            state.current_artifacts_dir,
            state.current_prompt,
            label="Full feedback prompt",
        )
        return None  # continue loop

    from sase.axe.run_agent_exec_plan_accept import handle_accepted_plan

    return handle_accepted_plan(plan_result, ctx, state)
