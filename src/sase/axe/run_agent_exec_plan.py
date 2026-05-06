"""Plan and question handlers for the agent execution loop."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.run_agent_exec_plan_artifacts import (
    get_embedded_workflow_refs,
    write_plan_path_artifact,
)
from sase.axe.run_agent_exec_plan_sdd import (
    build_epic_plan_ref,
    build_saved_plan_ref,
    build_sdd_plan_ref,
    commit_sdd_files_for_exec_plan,
    infer_epic_legend_bead_id,
    plan_kind_for_action,
)
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    format_qa_for_prompt,
    handle_questions_flow,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
    update_step_marker_chat_path,
)
from sase.axe.runner_utils import reset_killed, was_killed
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    plan_chain_agent_name,
    plan_chain_feedback_suffix,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)

_build_epic_plan_ref = build_epic_plan_ref
_build_saved_plan_ref = build_saved_plan_ref
_build_sdd_plan_ref = build_sdd_plan_ref
_get_embedded_workflow_refs = get_embedded_workflow_refs
_infer_epic_legend_bead_id = infer_epic_legend_bead_id
_plan_kind_for_action = plan_kind_for_action
_write_plan_path_artifact = write_plan_path_artifact


def _accepted_plan_action_for_meta(plan_result: Any) -> str:
    if plan_result.action == "approve" and not plan_result.run_coder:
        return "commit"
    return str(plan_result.action)


def _commit_sdd_files(
    workspace_dir: str, plan_name: str, *, plan_kind: str = "tales"
) -> None:
    commit_sdd_files_for_exec_plan(
        workspace_dir,
        plan_name,
        plan_kind=plan_kind,
        logger=logger,
        subprocess_run=subprocess.run,
    )


def _update_coder_model_meta(
    plan_result: Any,
    ctx: AgentExecContext,
    state: LoopState,
) -> None:
    """Update the coder's ``agent_meta.json`` if the picker model differs from the planner's."""
    if not plan_result.coder_model or plan_result.coder_model == ctx.agent_model:
        return
    from sase.llm_provider.registry import resolve_model_provider

    resolved_provider, resolved_model = resolve_model_provider(plan_result.coder_model)
    update_meta_field(state.current_artifacts_dir, "model", resolved_model)
    if resolved_provider:
        update_meta_field(
            state.current_artifacts_dir, "llm_provider", resolved_provider
        )


def _agent_name_for_suffix(ctx: AgentExecContext, suffix: str | None) -> str | None:
    if not ctx.agent_name or not suffix:
        return None
    return plan_chain_agent_name(ctx.agent_name, suffix)


def _record_workflow_metadata(
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
        "questions_submitted_at",
    }
    for key, value in relationships.items():
        if key in retained_fields and value is not None and value != "":
            update_meta_field(artifacts_dir, key, value)


def handle_plan_marker(
    plan_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Handle a plan marker left by ``sase plan``.

    Returns a loop-outcome string to break the loop, or ``None`` to continue.
    """
    normalize_handoff_interruption_state(state.current_artifacts_dir)
    # Only set the ".plan" suffix on the original workflow entry;
    # feedback round agents (suffix ".2", ".3", …) keep theirs.
    if state.feedback_round == 0:
        update_meta_suffix(state.current_artifacts_dir, PLAN_CHAIN_PLAN_SUFFIX)

    plan_submitted_at = datetime.now(UTC).isoformat()
    _record_workflow_metadata(
        state.current_artifacts_dir,
        {
            "plan_submitted_at": plan_submitted_at,
            "plan_path": plan_data.get("plan_file"),
            "changespec_name": ctx.cl_name,
        },
    )

    from sase.llm_provider._plan_utils import handle_plan_approval

    # Clear the killed flag set by the plan command's SIGTERM
    # so the poll loop only exits on a NEW kill signal.
    reset_killed()
    plan_result = handle_plan_approval(
        plan_data.get("plan_file"),
        str(uuid.uuid4()),
        killed_check=was_killed,
        agent_name=ctx.agent_name,
        agent_model=ctx.agent_model,
        agent_llm_provider=ctx.agent_llm_provider,
    )
    if plan_result is None and was_killed():
        return "killed"
    if plan_result is None:
        return "plan_rejected"

    # Write plan_path.json so the TUI can show the plan
    # in the file panel for the .plan agent entry.
    _write_plan_path_artifact(state.current_artifacts_dir, plan_result.plan_file)
    _record_workflow_metadata(
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
    planner_agent = f"{ctx.agent_name}{_planner_suffix}" if ctx.agent_name else None
    _planner_extra = format_extra_sections(state.current_artifacts_dir)
    _planner_chat = save_chat_history(
        prompt=state.current_prompt,
        response=plan_response,
        workflow="ace-run",
        agent=planner_agent,
        timestamp=ctx.timestamp,
        extra_sections=_planner_extra,
        branch_or_workspace=ctx.cl_name,
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

        feedback_submitted_at = datetime.now(UTC).isoformat()
        update_meta_field(
            state.current_artifacts_dir,
            "feedback_submitted_at",
            feedback_submitted_at,
        )

        suffix = plan_chain_feedback_suffix(state.feedback_round)
        feedback_agent_name = _agent_name_for_suffix(ctx, suffix)
        _record_workflow_metadata(
            state.current_artifacts_dir,
            {
                "feedback_submitted_at": feedback_submitted_at,
                "followup_agent_name": feedback_agent_name,
                "plan_path": plan_result.plan_file,
            },
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
                "source_plan_agent_name": _agent_name_for_suffix(
                    ctx, PLAN_CHAIN_PLAN_SUFFIX
                ),
            },
        )

        # Reconstruct prompt: original + all Q&A + requirements
        base = state.original_prompt
        for qa in state.qa_sections:
            base += "\n\n" + qa
        reqs = "\n".join(f"- {fb}" for fb in state.feedback_bullets)
        state.current_prompt = f"{base}\n\n### Additional Requirements\n\n{reqs}"
        return None  # continue loop

    update_meta_field(state.current_artifacts_dir, "plan_approved", True)
    update_meta_field(
        state.current_artifacts_dir,
        "plan_action",
        _accepted_plan_action_for_meta(plan_result),
    )

    # Write SDD files (spec + plan) to project
    from sase.sdd.beads import get_sdd_config
    from sase.sdd.files import (
        commit_sdd_files,
        expand_prompt_for_spec,
        get_sdd_dir,
        write_sdd_files,
    )

    sdd_plan_name: str | None = None
    sdd_plan_path: Path | None = None
    version_controlled = True  # safe default (VC path is the no-op path)
    sdd_dir = Path(ctx.workspace_dir)
    try:
        version_controlled = get_sdd_config()
        sdd_dir = get_sdd_dir(ctx.workspace_dir, ctx.workspace_num, version_controlled)
        sdd_plan_name = os.path.splitext(os.path.basename(plan_result.plan_file))[0]
        try:
            expanded = expand_prompt_for_spec(state.current_prompt)
        except Exception:
            logger.warning(
                "Spec prompt expansion failed, using raw prompt", exc_info=True
            )
            expanded = state.current_prompt
        plan_kind = _plan_kind_for_action(plan_result.action)
        sdd_prompt_path_obj, sdd_plan_path = write_sdd_files(
            sdd_dir,
            sdd_plan_name,
            expanded,
            plan_result.plan_file,
            plan_kind=plan_kind,
        )
        state.sdd_spec_path = str(sdd_prompt_path_obj)
        _record_workflow_metadata(
            state.current_artifacts_dir,
            {
                "sdd_prompt_path": str(sdd_prompt_path_obj),
                "sdd_plan_path": str(sdd_plan_path),
            },
        )
        if not version_controlled:
            commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")
    except Exception:
        logger.warning("SDD file generation failed", exc_info=True)

    # Unified SDD commit: epics always need committed files (the #gh
    # pre-step wipes uncommitted files); other actions respect commit_plan.
    should_commit = (
        plan_result.commit_plan
        if plan_result.action not in ("epic", "legend")
        else True
    )
    if should_commit and sdd_plan_name:
        if version_controlled:
            plan_kind = _plan_kind_for_action(plan_result.action)
            _commit_sdd_files(ctx.workspace_dir, sdd_plan_name, plan_kind=plan_kind)
        else:
            commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")

    if not plan_result.run_coder and plan_result.action not in ("epic", "legend"):
        return "plan_committed"

    # VCS workflow tag prefix for follow-up agents
    vcs_prefix = ctx.vcs_tag or ""

    # Reconstruct non-VCS embedded workflow refs (e.g. #propose,
    # #commit) to append after the main prompt so their post-steps
    # run after the follow-up agent.
    embedded_refs = get_embedded_workflow_refs(state.current_artifacts_dir, ctx.vcs_tag)

    # Use coder_model override from plan approval if provided,
    # otherwise inherit the planner's model.
    if plan_result.coder_model:
        model_prefix = f"%model:{plan_result.coder_model}\n"
    elif ctx.agent_model:
        model_prefix = f"%model:{ctx.agent_model}\n"
    else:
        model_prefix = ""

    if plan_result.action in ("epic", "legend"):
        # Ensure beads are initialized before spawning epic agent
        from sase.sdd.beads import ensure_beads_initialized

        ensure_beads_initialized(ctx.workspace_dir, ctx.workspace_num)
        legend_bead_id = (
            _infer_epic_legend_bead_id(
                sdd_plan_path=sdd_plan_path,
                workspace_dir=ctx.workspace_dir,
                sdd_dir=sdd_dir,
            )
            if plan_result.action == "epic"
            else None
        )

        # Epic/legend: spawn a follow-up agent to create the container bead.
        state.current_role_suffix = (
            ".epic" if plan_result.action == "epic" else ".legend"
        )
        state.agent_step += 1
        if state.agent_step == 2 and ctx.agent_name:
            promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
        state.current_artifacts_dir = create_followup_artifacts(
            ctx.project_name,
            ctx.agent_meta,
            state.current_role_suffix,
            convert_timestamp_to_artifacts_format(ctx.timestamp),
            workspace_num=ctx.workspace_num,
            agent_name_override=f"{ctx.agent_name}{state.current_role_suffix}"
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
            relationships={
                "plan_path": plan_result.plan_file,
                "sdd_prompt_path": str(state.sdd_spec_path)
                if state.sdd_spec_path
                else None,
                "sdd_plan_path": str(sdd_plan_path) if sdd_plan_path else None,
                "legend_bead_id": (
                    legend_bead_id if plan_result.action == "epic" else None
                ),
                "changespec_name": ctx.cl_name,
                "source_plan_agent_name": _agent_name_for_suffix(
                    ctx, PLAN_CHAIN_PLAN_SUFFIX
                ),
            },
        )
        update_meta_field(
            state.current_artifacts_dir,
            "epic_started_at" if plan_result.action == "epic" else "legend_started_at",
            datetime.now(UTC).isoformat(),
        )
        _update_coder_model_meta(plan_result, ctx, state)
        if plan_result.action == "epic":
            plan_ref = _build_epic_plan_ref(
                sdd_plan_path=sdd_plan_path,
                sdd_dir=sdd_dir,
                workspace_dir=ctx.workspace_dir,
                sdd_plan_name=sdd_plan_name,
                version_controlled=version_controlled,
                fallback_plan_file=plan_data["plan_file"],
            )
            legend_bead_id = _infer_epic_legend_bead_id(
                sdd_plan_path=sdd_plan_path,
                workspace_dir=ctx.workspace_dir,
                sdd_dir=sdd_dir,
            )
            if legend_bead_id:
                plan_ref = f"{plan_ref},{legend_bead_id}"
            xprompt_name = "bd/new_epic"
        else:
            plan_ref = _build_sdd_plan_ref(
                sdd_plan_path=sdd_plan_path,
                sdd_dir=sdd_dir,
                workspace_dir=ctx.workspace_dir,
                sdd_plan_name=sdd_plan_name,
                version_controlled=version_controlled,
                fallback_plan_file=plan_data["plan_file"],
                plan_kind="legends",
            )
            xprompt_name = "bd/new_legend"
        state.current_prompt = (
            f"{model_prefix}{vcs_prefix}#{xprompt_name}:{plan_ref}\n{embedded_refs}"
        )
    else:
        # Approve: spawn coder with plan as prompt
        state.current_role_suffix = PLAN_CHAIN_CODER_SUFFIX

        # Point SASE_PLAN at the committed in-repo plan file only when the
        # approval committed that file. No-commit approvals must hand off the
        # archived plan because VCS workflow pre-steps may stash local SDD files.
        if plan_result.commit_plan and sdd_plan_path and sdd_plan_path.exists():
            os.environ["SASE_PLAN"] = str(sdd_plan_path)
        else:
            os.environ["SASE_PLAN"] = plan_result.plan_file

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
                "sdd_prompt_path": str(state.sdd_spec_path)
                if state.sdd_spec_path
                else None,
                "sdd_plan_path": str(sdd_plan_path) if sdd_plan_path else None,
                "changespec_name": ctx.cl_name,
                "source_plan_agent_name": _agent_name_for_suffix(
                    ctx, PLAN_CHAIN_PLAN_SUFFIX
                ),
            },
        )
        _update_coder_model_meta(plan_result, ctx, state)
        coder_extra = ""
        if plan_result.coder_prompt:
            coder_extra = f"\n\nAdditional instructions:\n{plan_result.coder_prompt}"
            # If the custom prompt contains its own %model/%m directive,
            # skip the inherited model prefix to avoid a duplicate error.
            if model_prefix:
                from sase.xprompt.directives import has_model_directive

                if has_model_directive(plan_result.coder_prompt):
                    model_prefix = ""
        # By default the coder starts with a fresh context window; the plan
        # file itself is the hand-off artifact. Set SASE_CODER_INHERIT_PLANNER_CHAT=1
        # to restore the old behavior of prepending #resume:<planner_name> so
        # the coder inherits the planner's full chat transcript.
        resume_prefix = ""
        if ctx.agent_name and os.environ.get("SASE_CODER_INHERIT_PLANNER_CHAT") == "1":
            if state.agent_step == 2:
                planner_name = f"{ctx.agent_name}.plan"
            else:
                planner_name = f"{ctx.agent_name}.{state.agent_step - 1}"
            resume_prefix = f"#resume:{planner_name} "

        if plan_result.commit_plan:
            coder_plan_ref = _build_saved_plan_ref(
                sdd_plan_path=sdd_plan_path,
                sdd_dir=sdd_dir,
                workspace_dir=ctx.workspace_dir,
                version_controlled=version_controlled,
                fallback_plan_file=plan_result.plan_file,
            )
        else:
            coder_plan_ref = plan_result.plan_file

        state.current_prompt = (
            f"{model_prefix}{resume_prefix}{vcs_prefix}"
            f"@{coder_plan_ref}\n\n"
            "The above plan has been reviewed and approved. "
            f"Implement it now.{coder_extra}\n{embedded_refs}"
        )

    return None  # continue loop


def handle_questions_marker(
    q_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Handle a questions marker left by ``sase questions``.

    Returns a loop-outcome string to break the loop, or ``None`` to continue.
    """
    normalize_handoff_interruption_state(state.current_artifacts_dir)
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
    _record_workflow_metadata(state.current_artifacts_dir, question_relationships)

    # Save a chat file for the questions step
    from sase.history.chat import save_chat_history
    from sase.history.chat_extras import format_extra_sections

    _q_suffix = (
        f"{previous_role_suffix}{PLAN_CHAIN_QUESTION_SUFFIX}"
        if re.match(r"^\.\d+$", previous_role_suffix)
        else state.current_role_suffix or PLAN_CHAIN_QUESTION_SUFFIX
    )
    _q_agent = f"{ctx.agent_name}{_q_suffix}" if ctx.agent_name else None
    _q_extra = format_extra_sections(state.current_artifacts_dir)
    _q_chat = save_chat_history(
        prompt=state.current_prompt,
        response=format_qa_for_prompt(q_data.get("questions", []), response),
        workflow="ace-run",
        agent=_q_agent,
        timestamp=ctx.timestamp,
        extra_sections=_q_extra,
        branch_or_workspace=ctx.cl_name,
    )
    state.saved_chat_paths.append((_q_suffix, _q_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)

    state.agent_step += 1
    if state.agent_step == 2 and ctx.agent_name:
        promote_to_workflow(
            ctx.artifacts_dir,
            ctx.agent_name,
            role_suffix=PLAN_CHAIN_QUESTION_SUFFIX,
        )
    state.current_artifacts_dir = create_followup_artifacts(
        ctx.project_name,
        ctx.agent_meta,
        state.current_role_suffix,
        convert_timestamp_to_artifacts_format(ctx.timestamp),
        workspace_num=ctx.workspace_num,
        agent_name_override=plan_chain_agent_name(
            ctx.agent_name,
            plan_chain_feedback_suffix(state.agent_step - 1),
        )
        if ctx.agent_name
        else None,
        workflow_name=ctx.agent_name,
        relationships={
            **question_relationships,
            "source_plan_agent_name": _agent_name_for_suffix(ctx, previous_role_suffix),
        },
    )
    qa_text = format_qa_for_prompt(q_data.get("questions", []), response)
    state.qa_sections.append(qa_text)
    state.current_prompt = state.current_prompt + "\n\n" + qa_text

    # Update SDD prompt snapshot with Q&A answers
    if state.sdd_spec_path is not None:
        try:
            from sase.sdd.files import update_spec_with_qa

            update_spec_with_qa(Path(state.sdd_spec_path), qa_text)
        except Exception:
            pass  # Best effort

    return None  # continue loop
