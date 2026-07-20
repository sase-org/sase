"""Questions marker handling for the agent execution loop."""

from __future__ import annotations

import json
import logging
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
    assemble_question_followup_prompt,
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
)
from sase.axe.run_agent_wait import wait_for_runner_slot
from sase.axe.runner_signals import reset_killed
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_PLAN_SUFFIX,
    allocate_agent_family_child_suffix,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
    is_root_question_suffix,
    plan_chain_agent_name,
    question_followup_suffix_template,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)

_store_followup_prompt_artifact = store_followup_prompt_artifact


def _interrupted_phase_meta(
    artifacts_dir: str,
    fallback_meta: dict[str, Any],
) -> dict[str, Any]:
    """Return the interrupted phase's ``agent_meta.json`` as follow-up base meta.

    A code-phase question continuation must inherit the concrete worker
    provider/model ``handle_accepted_plan`` recorded for the interrupted phase,
    not the planner metadata carried in ``ctx.agent_meta``. Falls back to
    *fallback_meta* when the file is missing or unreadable.
    """
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback_meta
    return loaded if isinstance(loaded, dict) and loaded else fallback_meta


def _meta_family_role(meta: dict[str, Any]) -> str | None:
    role = meta.get("agent_family_role")
    return role if isinstance(role, str) and role else None


def _fallback_question_suffix(template: str, *, root_sequence: bool) -> str:
    from sase.agent.names import render_agent_name_template

    token = "1" if root_sequence else "0"
    return render_agent_name_template(template, token)


def _update_sdd_prompt_snapshot_qa(
    ctx: AgentExecContext,
    state: LoopState,
    merged_qa_text: str,
) -> None:
    """Update a prompt snapshot and commit machine-made external-store writes.

    In-tree snapshots remain part of the agent's normal workspace commit flow.
    External SDD stores are committed here so a SASE-authored Q&A update never
    becomes unclaimed work for the commit finalizer.
    """
    if state.sdd_spec_path is None:
        return

    from sase.sdd.files import commit_sdd_store_files, set_prompt_qa
    from sase.sdd.store import resolve_sdd_store

    prompt_path = Path(state.sdd_spec_path)
    set_prompt_qa(prompt_path, merged_qa_text)

    store = resolve_sdd_store(ctx.workspace_dir, ctx.workspace_num or 1)
    if store.is_in_tree:
        return

    commit_sdd_store_files(
        store,
        f"Add Q&A to {prompt_path.stem} prompt",
        auto_commit_type="sdd",
        paths=[prompt_path],
        artifacts_dir=state.current_artifacts_dir,
    )


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
    base_meta = _interrupted_phase_meta(state.current_artifacts_dir, ctx.agent_meta)
    interrupted_role = _meta_family_role(base_meta)
    first_family_agent_question = state.agent_step == 1
    first_plan_agent_question = first_family_agent_question and (
        canonical_plan_chain_suffix(previous_role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
    )
    interrupted_suffix: str | None
    if first_plan_agent_question:
        interrupted_suffix = PLAN_CHAIN_PLAN_SUFFIX
    elif first_family_agent_question:
        interrupted_suffix = f"{AGENT_FAMILY_SEPARATOR}0"
    else:
        interrupted_suffix = canonical_plan_chain_suffix(previous_role_suffix)
    if interrupted_suffix is None:
        interrupted_suffix = (
            canonical_plan_chain_suffix(base_meta.get("role_suffix"))
            or f"{AGENT_FAMILY_SEPARATOR}0"
        )
    if first_family_agent_question:
        update_meta_suffix(state.current_artifacts_dir, interrupted_suffix)

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
        reacquire_runner_slot=lambda claim: wait_for_runner_slot(
            state.current_artifacts_dir,
            ctx.cl_name,
            Path(state.current_artifacts_dir).name,
            base_meta,
            wait_runners=None,
            wait_priority=None,
            claim=claim,
        ),
        run_started_at=(
            base_meta.get("run_started_at")
            if isinstance(base_meta.get("run_started_at"), str)
            else None
        ),
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

    _q_suffix = interrupted_suffix
    _q_agent = agent_name_for_suffix(ctx, _q_suffix)
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
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
    )
    state.saved_chat_paths.append((_q_suffix, _q_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)

    state.agent_step += 1
    if first_family_agent_question and state.agent_step == 2 and ctx.agent_name:
        promote_to_workflow(
            ctx.artifacts_dir,
            ctx.agent_name,
            role_suffix=interrupted_suffix,
        )
    root_sequence = (
        first_family_agent_question and not first_plan_agent_question
    ) or is_root_question_suffix(
        interrupted_suffix,
        agent_family_role=interrupted_role,
    )
    suffix_template = (
        f"{AGENT_FAMILY_SEPARATOR}@"
        if root_sequence
        else question_followup_suffix_template(
            interrupted_suffix,
            agent_family_role=interrupted_role,
        )
    )
    followup_suffix = (
        allocate_agent_family_child_suffix(
            ctx.agent_name,
            suffix_template,
            extra_reserved_suffixes=(
                *[suffix for suffix, _path in state.saved_chat_paths if suffix],
                interrupted_suffix,
            ),
        )
        if ctx.agent_name
        else _fallback_question_suffix(
            suffix_template,
            root_sequence=root_sequence,
        )
    )
    state.current_role_suffix = followup_suffix
    followup_role = (
        "q"
        if root_sequence
        else agent_family_role_for_suffix(
            followup_suffix,
            agent_family_role=interrupted_role,
        )
    )
    # Inherit the interrupted phase's concrete model/provider (e.g. the worker
    # model that ``handle_accepted_plan`` wrote for the code phase) instead of
    # the initial planner metadata in ``ctx.agent_meta``.
    state.current_artifacts_dir = create_followup_artifacts(
        ctx.project_name,
        base_meta,
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
        agent_family_role=followup_role,
        relationships={
            **question_relationships,
            "source_plan_agent_name": _q_agent,
        },
    )
    # Rebuild from the current phase base (code/feedback/planner prompt) so a
    # code-phase question keeps the code prompt and its ``%model`` directive.
    state.current_prompt = assemble_question_followup_prompt(
        state.question_base_prompt,
        state.qa_rounds,
    )
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
            _update_sdd_prompt_snapshot_qa(ctx, state, merged_qa_text)
        except Exception:
            logger.warning("SDD prompt Q&A snapshot update failed", exc_info=True)

    return None  # continue loop
