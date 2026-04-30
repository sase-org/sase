"""Agent execution loop for the run agent runner.

Contains the core while-loop that runs workflow steps with retry,
plan approval, and question-flow handling.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from sase.axe.run_agent_exec_plan import (
    _get_embedded_workflow_refs as _get_embedded_workflow_refs,
    handle_plan_marker,
    handle_questions_marker,
)
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_helpers import (
    extract_step_output_and_diff_path,
    is_workflow_noop,
    read_and_delete_marker,
)
from sase.axe.run_agent_phases import build_done_marker
from sase.axe.runner_utils import reset_killed, was_killed
from sase.history.chat import save_chat_history
from sase.telemetry.metrics import AGENT_KILLS
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.retry_config import RetryState, get_retry_config


@dataclass
class AgentExecContext:
    """Immutable configuration the execution loop needs from the runner."""

    cl_name: str
    project_file: str
    workspace_dir: str
    output_path: str
    workspace_num: int
    timestamp: str
    update_target: str
    project_name: str
    is_home_mode: bool
    artifacts_dir: str
    artifacts_timestamp: str
    vcs_tag: str | None
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_vcs_provider: str | None
    agent_hidden: bool
    agent_meta: dict[str, Any]
    local_xprompts: dict[str, Any]
    wait_chats: list[str] = field(default_factory=list)


@dataclass
class _AgentExecResult:
    """Result from the execution loop."""

    success: bool
    outcome: str = "completed"
    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    current_artifacts_dir: str = ""
    step_output: dict[str, Any] | None = None


@dataclass
class LoopState:
    """Mutable state for the execution loop."""

    current_prompt: str
    current_role_suffix: str
    current_artifacts_dir: str
    loop_outcome: str
    sdd_spec_path: str | None
    original_prompt: str
    qa_sections: list[str] = field(default_factory=list)
    feedback_bullets: list[str] = field(default_factory=list)
    feedback_round: int = 0
    agent_step: int = 1
    saved_chat_paths: list[tuple[str, str]] = field(default_factory=list)


def _resolve_workflow_project(ctx: AgentExecContext) -> str | None:
    """Return project scope for xprompt/workflow resolution."""
    if ctx.is_home_mode:
        return None
    return ctx.project_name


def _finalize_loop(
    ctx: AgentExecContext,
    state: LoopState,
    tracker: RetryTracker,
    result: Any,
) -> _AgentExecResult:
    """Post-loop cleanup: retry state, done marker, result construction."""
    # Clean up retry state
    RetryState.delete_from(ctx.artifacts_dir)
    if "SASE_MODEL_OVERRIDE" in os.environ:
        del os.environ["SASE_MODEL_OVERRIDE"]

    # Build retry metadata for done.json
    _retry_meta: dict[str, Any] | None = None
    if tracker.retry_count > 0 or tracker.using_fallback:
        _retry_meta = {
            "retry_count": tracker.retry_count,
            "retry_errors": tracker.retry_errors,
            "used_fallback": tracker.using_fallback,
        }
        if tracker.using_fallback and tracker.retry_cfg:
            _retry_meta["fallback_model"] = tracker.retry_cfg.fallback_model

    # Clean up SASE_ARTIFACTS_DIR and SASE_PLAN env vars
    os.environ.pop("SASE_ARTIFACTS_DIR", None)
    os.environ.pop("SASE_PLAN", None)

    # Compute the final agent name for the done marker.
    # Multi-agent workflows use the last child name; single-agent keeps original.
    _done_agent_name: str | None
    if state.agent_step > 1 and ctx.agent_name:
        if state.current_role_suffix in (".code", ".epic"):
            _done_agent_name = f"{ctx.agent_name}{state.current_role_suffix}"
        else:
            _done_agent_name = f"{ctx.agent_name}.{state.agent_step}"
    else:
        _done_agent_name = ctx.agent_name

    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = []
    image_paths: list[str] = []
    step_output: dict[str, Any] | None = None

    # Save chat history for ALL outcomes so the file referenced by
    # SASE_AGENT_CHAT_PATH always exists (even for killed/plan_rejected).
    if state.loop_outcome == "completed":
        assert result is not None
        response_content = result.response_text or ""
    else:
        response_content = ""

    extra = format_extra_sections(state.current_artifacts_dir)
    saved_path = save_chat_history(
        prompt=state.current_prompt,
        response=response_content,
        workflow="ace-run",
        timestamp=ctx.timestamp,
        extra_sections=extra,
        branch_or_workspace=ctx.cl_name,
    )
    print(f"\nChat history saved to: {saved_path}")

    if state.loop_outcome == "completed":
        # Cross-link all chat files in multi-step workflows
        state.saved_chat_paths.append(
            (state.current_role_suffix or ".code", saved_path)
        )
        if len(state.saved_chat_paths) > 1:
            from sase.history.chat_links import (
                append_links_to_chat,
                build_linked_chats_section,
            )

            for role, path in state.saved_chat_paths:
                links_section = build_linked_chats_section(
                    state.saved_chat_paths, current_role=role
                )
                append_links_to_chat(os.path.expanduser(path), links_section)

        # Read plan_path from plan_path.json if written by claude.py
        plan_path: str | None = None
        plan_path_file = os.path.join(state.current_artifacts_dir, "plan_path.json")
        try:
            with open(plan_path_file, encoding="utf-8") as f:
                plan_path = json.load(f).get("plan_path")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        # Extract step_output and diff_path from workflow_state.json
        step_output, diff_path = extract_step_output_and_diff_path(
            state.current_artifacts_dir
        )
        from sase.attachments.markdown_pdf import render_markdown_pdf_attachments
        from sase.axe.image_attachments import (
            collect_agent_image_paths,
            collect_agent_markdown_paths,
        )

        include_head_commit = bool(
            step_output
            and any(
                step_output.get(key)
                for key in (
                    "meta_new_commit",
                    "meta_pr_url",
                )
            )
        )
        workspace_dir = getattr(ctx, "workspace_dir", os.getcwd())
        base_files = [path for path in [saved_path, diff_path] if path]
        markdown_paths = collect_agent_markdown_paths(
            workspace_dir,
            diff_path=diff_path,
            include_head_commit=include_head_commit,
            existing_files=base_files,
            artifacts_dir=state.current_artifacts_dir,
        )
        markdown_pdf_paths = render_markdown_pdf_attachments(
            markdown_paths,
            workspace_dir=workspace_dir,
            artifacts_dir=state.current_artifacts_dir,
        )
        image_paths = collect_agent_image_paths(
            workspace_dir,
            diff_path=diff_path,
            include_head_commit=include_head_commit,
            existing_files=[*base_files, *markdown_pdf_paths],
        )

        # Detect noop: workflow completed but launched zero agents
        completed_outcome = (
            "noop" if is_workflow_noop(state.current_artifacts_dir) else "completed"
        )

        # Write done marker
        done_marker = build_done_marker(
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.output_path,
            completed_outcome,
            agent_name=_done_agent_name,
            agent_model=ctx.agent_model,
            agent_llm_provider=ctx.agent_llm_provider,
            agent_vcs_provider=ctx.agent_vcs_provider,
            agent_hidden=ctx.agent_hidden,
            response_path=saved_path,
            step_output=step_output,
            diff_path=diff_path,
            plan_path=plan_path,
            markdown_pdf_paths=markdown_pdf_paths,
            image_paths=image_paths,
            retry_metadata=_retry_meta,
        )
        done_path = os.path.join(state.current_artifacts_dir, "done.json")
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_marker, f, indent=2)
        print(f"Done marker written to: {done_path}")
    else:
        # plan_rejected, killed, or failed_retried (spawn-on-retry handoff)
        # For failed_retried, the failing parent has handed off to a fresh
        # detached child agent; record outcome="failed" + retry-chain forward
        # pointers so the loader can render the chain.
        retried_as_timestamp: str | None = None
        retry_chain_root_timestamp: str | None = None
        retry_error_category: str | None = None
        if state.loop_outcome == "failed_retried":
            actual_outcome = "failed"
            try:
                meta_path = os.path.join(ctx.artifacts_dir, "agent_meta.json")
                with open(meta_path, encoding="utf-8") as _f:
                    _meta = json.load(_f)
                if isinstance(_meta, dict):
                    retried_as_timestamp = _meta.get("retried_as_timestamp")
                    retry_chain_root_timestamp = _meta.get("retry_chain_root_timestamp")
                    retry_error_category = _meta.get("retry_error_category")
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
        else:
            actual_outcome = state.loop_outcome

        done_marker = build_done_marker(
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.output_path,
            actual_outcome,
            agent_name=_done_agent_name,
            agent_model=ctx.agent_model,
            agent_hidden=ctx.agent_hidden,
            response_path=saved_path,
            retry_metadata=_retry_meta,
            retried_as_timestamp=retried_as_timestamp,
            retry_chain_root_timestamp=retry_chain_root_timestamp,
            retry_error_category=retry_error_category,
        )
        done_path = os.path.join(state.current_artifacts_dir, "done.json")
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_marker, f, indent=2)
        print(f"Done marker written to: {done_path} (outcome: {state.loop_outcome})")

    # For multi-step workflows the root artifacts directory (ctx.artifacts_dir)
    # differs from the last step's directory (state.current_artifacts_dir).
    # Write done.json to the root as well so that:
    #   - _get_active_agent_names counts the root as done → name stays reserved
    #   - claim_agent_name skips done artifacts → workflow_name is preserved
    #   - find_named_agent can discover the completed workflow from the root
    if state.current_artifacts_dir != ctx.artifacts_dir:
        root_done_path = os.path.join(ctx.artifacts_dir, "done.json")
        with open(root_done_path, "w", encoding="utf-8") as f:
            json.dump(done_marker, f, indent=2)

    return _AgentExecResult(
        success=state.loop_outcome == "completed",
        outcome=state.loop_outcome,
        saved_path=saved_path,
        diff_path=diff_path,
        markdown_pdf_paths=markdown_pdf_paths,
        image_paths=image_paths,
        current_artifacts_dir=state.current_artifacts_dir,
        step_output=step_output,
    )


def run_execution_loop(
    ctx: AgentExecContext,
    prompt: str,
) -> _AgentExecResult:
    """Run the agent workflow loop with retry, plan approval, and question handling.

    Returns an _AgentExecResult with the outcome.
    """
    from sase.xprompt.models import create_anonymous_workflow
    from sase.xprompt.workflow_runner import execute_workflow

    # Pre-set SASE_AGENT_CHAT_PATH so the commit stop hook (and
    # create_changespec_for_workflow) can reference the ace-run chat file.
    # The file won't exist yet — it's written in _finalize_loop — but the
    # COMMITS entry only stores the path string.
    from pathlib import Path

    from sase.history.chat import generate_chat_filename, get_chat_file_path

    chat_basename = generate_chat_filename(
        workflow="ace-run", branch_or_workspace=ctx.cl_name, timestamp=ctx.timestamp
    )
    predicted_chat_path = get_chat_file_path(chat_basename).replace(
        str(Path.home()), "~"
    )
    os.environ["SASE_AGENT_CHAT_PATH"] = predicted_chat_path

    tracker = RetryTracker(
        retry_cfg=get_retry_config(ctx.agent_llm_provider)
        if ctx.agent_llm_provider
        else None,
        attempt_start_epoch=time.time(),
    )
    state = LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
    )
    result = None

    while True:
        reset_killed()
        os.environ["SASE_ARTIFACTS_DIR"] = state.current_artifacts_dir
        anon_workflow = create_anonymous_workflow(state.current_prompt)
        if ctx.local_xprompts:
            anon_workflow.xprompts = ctx.local_xprompts

        named_args: dict[str, Any] = {
            "cl_name": ctx.cl_name,
            "workspace_num": ctx.workspace_num,
        }
        _repeat_iter_env = os.environ.get("SASE_REPEAT_ITERATION")
        _repeat_total_env = os.environ.get("SASE_REPEAT_TOTAL")
        if _repeat_iter_env is not None and _repeat_total_env is not None:
            try:
                named_args["n"] = int(_repeat_iter_env)
                named_args["N"] = int(_repeat_total_env)
            except ValueError:
                pass
        if ctx.wait_chats:
            named_args["wait_chats"] = ctx.wait_chats

        try:
            result = execute_workflow(
                anon_workflow.name,
                [],
                named_args,
                artifacts_dir=state.current_artifacts_dir,
                silent=True,
                workflow_obj=anon_workflow,
                project=_resolve_workflow_project(ctx),
            )
        except Exception as wf_exc:
            if not was_killed():
                action = handle_workflow_error(wf_exc, tracker, ctx, state)
                if action == "continue":
                    continue
                elif action == "break":
                    break
                else:
                    raise
            result = None

        # If the process wasn't killed, this is a normal completion.
        # When it WAS killed, invoke_agent() may have swallowed the
        # CalledProcessError and returned an error AIMessage instead
        # of raising, so we must check for markers in both paths.
        if not was_killed():
            break  # Normal completion

        # Check for marker files left by `sase plan` / `sase questions`
        plan_data = read_and_delete_marker(
            state.current_artifacts_dir, ".sase_plan_pending"
        )
        q_data = read_and_delete_marker(
            state.current_artifacts_dir, ".sase_questions_pending"
        )

        if plan_data:
            outcome = handle_plan_marker(plan_data, ctx, state)
            if outcome is not None:
                state.loop_outcome = outcome
                break
            continue
        elif q_data:
            outcome = handle_questions_marker(q_data, ctx, state)
            if outcome is not None:
                state.loop_outcome = outcome
                break
            continue
        else:
            # Killed by user (no marker)
            AGENT_KILLS.labels(reason="user").inc()
            state.loop_outcome = "killed"
            break

    return _finalize_loop(ctx, state, tracker, result)
