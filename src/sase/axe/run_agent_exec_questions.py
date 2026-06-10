"""Questions marker handling for the agent execution loop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.run_agent_exec_plan import (
    agent_name_for_suffix,
    record_workflow_metadata,
)
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import (
    build_qa_round,
    create_followup_artifacts,
    finalize_handoff_artifacts_as_completed,
    handle_questions_flow,
    merge_qa_for_prompt,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
    update_step_marker_chat_path,
    write_episode_trace_marker,
)
from sase.axe.runner_utils import reset_killed
from sase.plan_chain import (
    PLAN_CHAIN_QUESTION_SUFFIX,
    canonical_plan_chain_suffix,
    plan_chain_agent_name,
    plan_chain_feedback_round,
    plan_chain_feedback_suffix,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

_store_followup_prompt_artifact = store_followup_prompt_artifact


def handle_questions_marker(
    q_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Handle a questions marker left by ``sase questions``.

    Returns a loop-outcome string to break the loop, or ``None`` to continue.
    """
    normalize_handoff_interruption_state(state.current_artifacts_dir)
    finalize_handoff_artifacts_as_completed(state.current_artifacts_dir)
    previous_role_suffix = state.current_role_suffix
    state.current_role_suffix = PLAN_CHAIN_QUESTION_SUFFIX
    update_meta_suffix(
        state.current_artifacts_dir,
        state.current_role_suffix or PLAN_CHAIN_QUESTION_SUFFIX,
    )

    questions_submitted_at = datetime.now(UTC).isoformat()
    update_meta_field(
        state.current_artifacts_dir,
        "questions_submitted_at",
        questions_submitted_at,
    )

    # Clear the killed flag set by the questions command's
    # SIGTERM so the poll loop only exits on a NEW kill signal.
    reset_killed()
    response = handle_questions_flow(
        q_data.get("questions", []),
        state.current_artifacts_dir,
    )
    if response is None:
        return "killed"
    question_relationships = {
        "questions_submitted_at": questions_submitted_at,
        "question_request_path": response.get("_question_request_path"),
        "question_response_path": response.get("_question_response_path"),
        "question_session_id": response.get("_question_session_id"),
        "changespec_name": ctx.cl_name,
    }
    record_workflow_metadata(state.current_artifacts_dir, question_relationships)

    # Save a chat file for the questions step
    from sase.history.chat import save_chat_history
    from sase.history.chat_extras import format_extra_sections

    previous_suffix = canonical_plan_chain_suffix(previous_role_suffix)
    _q_suffix = (
        f"{previous_suffix}{PLAN_CHAIN_QUESTION_SUFFIX}"
        if plan_chain_feedback_round(previous_suffix) is not None
        else state.current_role_suffix or PLAN_CHAIN_QUESTION_SUFFIX
    )
    _q_agent = f"{ctx.agent_name}{_q_suffix}" if ctx.agent_name else None
    _q_extra = format_extra_sections(state.current_artifacts_dir)

    # Append this round before rendering so the chat transcript and the
    # follow-up prompt share the same monotonic merged section.
    state.qa_rounds.append(build_qa_round(q_data.get("questions", []), response))
    merged_qa_text = merge_qa_for_prompt(state.qa_rounds)

    _q_chat = save_chat_history(
        prompt=state.current_prompt,
        response=merged_qa_text,
        workflow="ace-run",
        agent=_q_agent,
        timestamp=ctx.timestamp,
        extra_sections=_q_extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=_q_agent,
    )
    state.saved_chat_paths.append((_q_suffix, _q_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)
    write_episode_trace_marker(
        state.current_artifacts_dir,
        chat_path=_q_chat,
        root_timestamp=ctx.artifacts_timestamp,
    )

    state.agent_step += 1
    if state.agent_step == 2 and ctx.agent_name:
        promote_to_workflow(
            ctx.artifacts_dir,
            ctx.agent_name,
            role_suffix=PLAN_CHAIN_QUESTION_SUFFIX,
        )
    followup_suffix = plan_chain_feedback_suffix(state.agent_step - 1)
    state.current_role_suffix = followup_suffix
    state.current_artifacts_dir = create_followup_artifacts(
        ctx.project_name,
        ctx.agent_meta,
        followup_suffix,
        convert_timestamp_to_artifacts_format(ctx.timestamp),
        workspace_num=ctx.workspace_num,
        agent_name_override=plan_chain_agent_name(
            ctx.agent_name,
            followup_suffix,
        )
        if ctx.agent_name
        else None,
        workflow_name=ctx.agent_name,
        relationships={
            **question_relationships,
            "source_plan_agent_name": agent_name_for_suffix(ctx, previous_role_suffix),
        },
    )
    state.current_prompt = state.original_prompt + "\n\n" + merged_qa_text
    _store_followup_prompt_artifact(
        state.current_artifacts_dir,
        state.current_prompt,
        label="Full question prompt",
    )

    # Update SDD prompt snapshot with the merged Q&A section so the
    # snapshot mirrors the prompt the follow-up agent will see (one
    # block, continuous numbering — not an appended per-round delta).
    if state.sdd_spec_path is not None:
        try:
            from sase.sdd.files import set_prompt_qa

            set_prompt_qa(Path(state.sdd_spec_path), merged_qa_text)
        except Exception:
            pass  # Best effort

    return None  # continue loop
