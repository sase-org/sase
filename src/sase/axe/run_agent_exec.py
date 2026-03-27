"""Agent execution loop for the run agent runner.

Contains the core while-loop that runs workflow steps with retry,
plan approval, and question-flow handling.
"""

import json
import os
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


@dataclass
class _AgentExecResult:
    """Result from the execution loop."""

    success: bool
    saved_path: str | None = None
    diff_path: str | None = None
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
    allow_retry: bool = True


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
    _done_agent_name = (
        f"{ctx.agent_name}.{state.agent_step}"
        if state.agent_step > 1 and ctx.agent_name
        else ctx.agent_name
    )

    saved_path: str | None = None
    diff_path: str | None = None
    step_output: dict[str, Any] | None = None

    if state.loop_outcome == "completed":
        assert result is not None
        # Extract response text for chat history
        response_content = result.response_text or ""

        # Prepare and save chat history
        extra = format_extra_sections(state.current_artifacts_dir)
        saved_path = save_chat_history(
            prompt=state.current_prompt,
            response=response_content,
            workflow="ace-run",
            timestamp=ctx.timestamp,
            extra_sections=extra,
        )
        print(f"\nChat history saved to: {saved_path}")

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
            retry_metadata=_retry_meta,
        )
        done_path = os.path.join(state.current_artifacts_dir, "done.json")
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_marker, f, indent=2)
        print(f"Done marker written to: {done_path}")
    else:
        # plan_rejected or killed
        done_marker = build_done_marker(
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.output_path,
            state.loop_outcome,
            agent_name=_done_agent_name,
            agent_model=ctx.agent_model,
            agent_hidden=ctx.agent_hidden,
            retry_metadata=_retry_meta,
        )
        done_path = os.path.join(state.current_artifacts_dir, "done.json")
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_marker, f, indent=2)
        print(f"Done marker written to: {done_path} (outcome: {state.loop_outcome})")

    return _AgentExecResult(
        success=state.loop_outcome == "completed",
        saved_path=saved_path,
        diff_path=diff_path,
        current_artifacts_dir=state.current_artifacts_dir,
        step_output=step_output,
    )


def run_execution_loop(ctx: AgentExecContext, prompt: str) -> _AgentExecResult:
    """Run the agent workflow loop with retry, plan approval, and question handling.

    Returns an _AgentExecResult with the outcome.
    """
    from sase.xprompt.models import create_anonymous_workflow
    from sase.xprompt.workflow_runner import execute_workflow

    tracker = RetryTracker(
        retry_cfg=get_retry_config(ctx.agent_llm_provider)
        if ctx.agent_llm_provider
        else None,
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

        try:
            result = execute_workflow(
                anon_workflow.name,
                [],
                {"cl_name": ctx.cl_name, "workspace_num": ctx.workspace_num},
                artifacts_dir=state.current_artifacts_dir,
                silent=True,
                workflow_obj=anon_workflow,
                project=ctx.project_name,
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
            state.loop_outcome = "killed"
            break

    return _finalize_loop(ctx, state, tracker, result)
