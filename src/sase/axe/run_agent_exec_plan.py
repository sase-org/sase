"""Plan, questions, and artifact helpers for the agent execution loop."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
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

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)


def _commit_sdd_files(workspace_dir: str, plan_name: str) -> None:
    """Commit SDD spec and plan files via ``sase commit`` before launching the epic agent.

    The ``#gh`` workflow pre-step runs ``git checkout . && git clean -fd`` which
    wipes uncommitted files.  Committing (and pushing) the SDD files first
    ensures the epic agent can still read them.
    """
    from sase.sdd.files import find_sdd_file

    base = Path(workspace_dir)
    fname = f"{plan_name}.md"
    spec_found = find_sdd_file(base, "specs", fname)
    plan_found = find_sdd_file(base, "plans", fname)
    files = [str(f) for f in (spec_found, plan_found) if f is not None]
    if not files:
        return
    message = f"chore: Add SDD spec and plan for {plan_name}"
    # -m / --message-file expects a file path, not a raw string.
    # handle_commit_command deletes the file after reading it.
    msg_fd, msg_path = tempfile.mkstemp(suffix=".txt", prefix="sase_sdd_msg_")
    try:
        os.write(msg_fd, message.encode())
    finally:
        os.close(msg_fd)
    cmd = ["sase", "commit", "-m", msg_path]
    for f in files:
        cmd.extend(["-f", f])
    result = subprocess.run(
        cmd,
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "sase commit for SDD files failed (exit %d): %s",
            result.returncode,
            result.stderr,
        )


def _write_plan_path_artifact(artifacts_dir: str, plan_path: str) -> None:
    """Write plan_path.json to the artifacts directory.

    This allows the TUI workflow loader to find the plan file and display
    it in the file panel for the .plan agent entry.
    """
    plan_path_file = Path(artifacts_dir) / "plan_path.json"
    try:
        with open(plan_path_file, "w", encoding="utf-8") as f:
            json.dump({"plan_path": plan_path}, f)
    except OSError:
        pass


def _get_embedded_workflow_refs(artifacts_dir: str, vcs_tag: str | None) -> str:
    """Reconstruct non-VCS embedded workflow refs from artifacts metadata.

    Reads embedded_workflows.json (written during workflow expansion before
    the agent is killed) and returns a string of workflow references
    (e.g., ``"#propose "``) to append to follow-up agent prompts so their
    post-steps run after the follow-up agent completes.
    """
    metadata_path = os.path.join(artifacts_dir, "embedded_workflows.json")
    try:
        with open(metadata_path, encoding="utf-8") as f:
            workflows = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""

    # Extract VCS workflow name from tag (e.g., "#hg:sase " -> "hg")
    vcs_name: str | None = None
    if vcs_tag:
        m = re.match(r"#(\w+)", vcs_tag)
        if m:
            vcs_name = m.group(1)

    # Only roll over workflows tagged with "rollover".
    # Backward compat: if no entry has a "tags" key at all, roll over
    # all non-VCS workflows (legacy behavior).
    has_any_tags = any("tags" in w for w in workflows)

    refs: list[str] = []
    for wf in workflows:
        name = wf["name"]
        wf_tags = wf.get("tags", [])
        if name == vcs_name or (vcs_tag and "vcs" in wf_tags):
            continue
        if has_any_tags and "rollover" not in wf_tags:
            continue
        args = wf.get("args", {})
        if not args:
            refs.append(f"#{name}")
        elif len(args) == 1:
            value = next(iter(args.values()))
            refs.append(f"#{name}:{value}")
        else:
            arg_parts = [f"{k}={v}" for k, v in args.items()]
            refs.append(f"#{name}({', '.join(arg_parts)})")

    if not refs:
        return ""
    return " ".join(refs) + " "


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
        update_meta_suffix(state.current_artifacts_dir, ".plan")

    update_meta_field(
        state.current_artifacts_dir,
        "plan_submitted_at",
        datetime.now(UTC).isoformat(),
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

    # Save a chat file for the planner step (the LLM response was lost
    # to SIGTERM, so we use a plan-file preview as the synthetic response).
    from sase.history.chat import save_chat_history
    from sase.history.chat_extras import format_extra_sections
    from sase.history.chat_links import format_plan_as_response

    plan_response = format_plan_as_response(plan_result.plan_file)
    planner_agent = f"{ctx.agent_name}.plan" if ctx.agent_name else None
    _planner_extra = format_extra_sections(state.current_artifacts_dir)
    _planner_chat = save_chat_history(
        prompt=state.current_prompt,
        response=plan_response,
        workflow="ace-run",
        agent=planner_agent,
        timestamp=ctx.timestamp,
        extra_sections=_planner_extra,
    )
    _planner_suffix = state.current_role_suffix or ".plan"
    state.saved_chat_paths.append((_planner_suffix, _planner_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _planner_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _planner_chat)

    # Feedback: spawn a new agent with the original prompt +
    # accumulated "Additional Requirements" section.
    if plan_result.action == "feedback":
        assert plan_result.feedback is not None
        state.feedback_round += 1
        state.feedback_bullets.append(plan_result.feedback)

        update_meta_field(
            state.current_artifacts_dir,
            "feedback_submitted_at",
            datetime.now(UTC).isoformat(),
        )

        suffix = f".{state.feedback_round + 1}"
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
            agent_name_override=f"{ctx.agent_name}.{state.agent_step}"
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
        )

        # Reconstruct prompt: original + all Q&A + requirements
        base = state.original_prompt
        for qa in state.qa_sections:
            base += "\n\n" + qa
        reqs = "\n".join(f"- {fb}" for fb in state.feedback_bullets)
        state.current_prompt = f"{base}\n\n### Additional Requirements\n\n{reqs}"
        state.allow_retry = False
        return None  # continue loop

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
        sdd_spec_path_obj, sdd_plan_path = write_sdd_files(
            sdd_dir, sdd_plan_name, expanded, plan_result.plan_file
        )
        state.sdd_spec_path = str(sdd_spec_path_obj)
        if not version_controlled:
            commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")
    except Exception:
        logger.warning("SDD file generation failed", exc_info=True)

    # Unified SDD commit: epics always need committed files (the #gh
    # pre-step wipes uncommitted files); other actions respect commit_plan.
    should_commit = plan_result.commit_plan if plan_result.action != "epic" else True
    if should_commit and sdd_plan_name:
        if version_controlled:
            _commit_sdd_files(ctx.workspace_dir, sdd_plan_name)
        else:
            commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")

    if not plan_result.run_coder and plan_result.action != "epic":
        return "plan_committed"

    # VCS workflow tag prefix for follow-up agents
    vcs_prefix = ctx.vcs_tag or ""

    # Reconstruct non-VCS embedded workflow refs (e.g. #propose,
    # #commit) to append after the main prompt so their post-steps
    # run after the follow-up agent.
    embedded_refs = _get_embedded_workflow_refs(
        state.current_artifacts_dir, ctx.vcs_tag
    )

    model_prefix = f"%model:{ctx.agent_model}\n" if ctx.agent_model else ""

    if plan_result.action == "epic":
        # Ensure beads are initialized before spawning epic agent
        from sase.sdd.beads import ensure_beads_initialized

        ensure_beads_initialized(ctx.workspace_dir, ctx.workspace_num)

        # Epic: spawn epic agent to create beads
        state.current_role_suffix = ".epic"
        state.agent_step += 1
        if state.agent_step == 2 and ctx.agent_name:
            promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
        state.current_artifacts_dir = create_followup_artifacts(
            ctx.project_name,
            ctx.agent_meta,
            state.current_role_suffix,
            convert_timestamp_to_artifacts_format(ctx.timestamp),
            workspace_num=ctx.workspace_num,
            agent_name_override=f"{ctx.agent_name}.{state.agent_step}"
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
        )
        if sdd_plan_path and sdd_plan_path.exists():
            plan_ref = str(sdd_plan_path.relative_to(Path(ctx.workspace_dir)))
        elif sdd_plan_name and not version_controlled:
            plan_ref = f".sase/sdd/plans/{sdd_plan_name}.md"
        elif sdd_plan_name:
            plan_ref = f"plans/{sdd_plan_name}.md"
        else:
            plan_ref = plan_data["plan_file"]
        state.current_prompt = (
            f"{model_prefix}{vcs_prefix}#bd/new_epic:{plan_ref}\n{embedded_refs}"
        )
    else:
        # Approve: spawn coder with plan as prompt
        state.current_role_suffix = ".code"

        # Point SASE_PLAN at the committed in-repo plan file so
        # the commit workflow can update its frontmatter without copying.
        if sdd_plan_path and sdd_plan_path.exists():
            os.environ["SASE_PLAN"] = str(sdd_plan_path)
        else:
            os.environ["SASE_PLAN"] = plan_data["plan_file"]

        state.agent_step += 1
        if state.agent_step == 2 and ctx.agent_name:
            promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
        state.current_artifacts_dir = create_followup_artifacts(
            ctx.project_name,
            ctx.agent_meta,
            state.current_role_suffix,
            convert_timestamp_to_artifacts_format(ctx.timestamp),
            workspace_num=ctx.workspace_num,
            agent_name_override=f"{ctx.agent_name}.{state.agent_step}"
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
        )
        coder_extra = ""
        if plan_result.coder_prompt:
            coder_extra = f"\n\nAdditional instructions:\n{plan_result.coder_prompt}"
        state.current_prompt = (
            f"{model_prefix}{vcs_prefix}"
            f"@{plan_data['plan_file']}\n\n"
            "The above plan has been reviewed and approved. "
            f"Implement it now.{coder_extra}\n{embedded_refs}"
        )

    state.allow_retry = False
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
    state.current_role_suffix += ".q"
    update_meta_suffix(
        state.current_artifacts_dir,
        state.current_role_suffix or ".q",
    )

    update_meta_field(
        state.current_artifacts_dir,
        "questions_submitted_at",
        datetime.now(UTC).isoformat(),
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

    # Save a chat file for the questions step
    from sase.history.chat import save_chat_history
    from sase.history.chat_extras import format_extra_sections

    _q_agent = f"{ctx.agent_name}.q" if ctx.agent_name else None
    _q_extra = format_extra_sections(state.current_artifacts_dir)
    _q_chat = save_chat_history(
        prompt=state.current_prompt,
        response=format_qa_for_prompt(response),
        workflow="ace-run",
        agent=_q_agent,
        timestamp=ctx.timestamp,
        extra_sections=_q_extra,
    )
    _q_suffix = state.current_role_suffix or ".q"
    state.saved_chat_paths.append((_q_suffix, _q_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)

    state.agent_step += 1
    if state.agent_step == 2 and ctx.agent_name:
        promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
    state.current_artifacts_dir = create_followup_artifacts(
        ctx.project_name,
        ctx.agent_meta,
        state.current_role_suffix,
        convert_timestamp_to_artifacts_format(ctx.timestamp),
        workspace_num=ctx.workspace_num,
        agent_name_override=f"{ctx.agent_name}.{state.agent_step}"
        if ctx.agent_name
        else None,
        workflow_name=ctx.agent_name,
    )
    qa_text = format_qa_for_prompt(response)
    state.qa_sections.append(qa_text)
    state.current_prompt = state.current_prompt + "\n\n" + qa_text

    # Update SDD spec file with Q&A answers
    if state.sdd_spec_path is not None:
        try:
            from sase.sdd.files import update_spec_with_qa

            update_spec_with_qa(Path(state.sdd_spec_path), qa_text)
        except Exception:
            pass  # Best effort

    state.allow_retry = False
    return None  # continue loop
