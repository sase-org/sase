"""Agent execution loop for the run agent runner."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from sase.axe.run_agent_exec_finalize import finalize_loop as _finalize_loop
from sase.axe.run_agent_exec_markers import (
    publish_phase_env as _publish_phase_env,
    write_done_marker_and_update_index as _write_done_marker_and_update_index,
)
from sase.axe.run_agent_exec_gate import handle_gate_marker
from sase.axe.run_agent_exec_monitor import handle_monitor_marker
from sase.axe.run_agent_exec_pipe import handle_pipe_marker
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_exec_plan_artifacts import (
    get_embedded_workflow_refs as _get_embedded_workflow_refs,
)
from sase.axe.run_agent_exec_questions import handle_questions_marker
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_exec_types import (
    AgentExecContext,
    AgentExecResult as _AgentExecResult,
    LoopState,
)
from sase.axe.run_agent_workspace_identity import (
    rebind_agent_workspace_identity_from_output,
)
from sase.axe.run_agent_helpers import (
    extract_step_output_and_diff_path,
    is_workflow_noop,
    read_and_delete_marker,
)
from sase.axe.runner_signals import killed_at, reset_killed, was_killed
from sase.agent.user_kill import has_user_kill_intent
from sase.history.chat import generate_chat_filename, get_chat_file_path
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.retry_config import get_retry_config
from sase.llm_provider._tool_calls import finalize_pending_tool_calls
from sase.telemetry.metrics import AGENT_KILLS

__all__ = [
    "AgentExecContext",
    "LoopState",
    "_AgentExecResult",
    "_finalize_loop",
    "_get_embedded_workflow_refs",
    "_publish_phase_env",
    "_resolve_workflow_project",
    "_write_done_marker_and_update_index",
    "extract_step_output_and_diff_path",
    "format_extra_sections",
    "is_workflow_noop",
    "run_execution_loop",
    "save_chat_history",
]


def _resolve_workflow_project(ctx: AgentExecContext) -> str | None:
    """Return project scope for xprompt/workflow resolution."""
    if ctx.is_home_mode:
        return None
    try:
        from sase.workspace_provider import get_workspace_name

        return get_workspace_name(ctx.workspace_dir)
    except Exception:
        return None


def _publish_predicted_chat_path(ctx: AgentExecContext) -> None:
    chat_basename = generate_chat_filename(
        workflow="ace-run",
        agent=ctx.agent_name,
        branch_or_workspace=ctx.cl_name,
        timestamp=ctx.timestamp,
    )
    predicted_chat_path = get_chat_file_path(chat_basename).replace(
        str(Path.home()), "~"
    )
    os.environ["SASE_AGENT_CHAT_PATH"] = predicted_chat_path


def _publish_root_timestamp(ctx: AgentExecContext) -> None:
    from sase.ace.tui.models._timestamps import normalize_to_14_digit

    root_basename = os.path.basename(ctx.artifacts_dir.rstrip("/"))
    os.environ["SASE_AGENT_ROOT_TIMESTAMP"] = (
        normalize_to_14_digit(root_basename) or root_basename
    )


def _build_named_args(ctx: AgentExecContext) -> dict[str, Any]:
    from sase.xprompt.workflow_runner import _WORKFLOW_INHERITED_VCS_TAG_ARG

    named_args: dict[str, Any] = {
        "patch_name": ctx.cl_name,
        "cl_name": ctx.cl_name,
        "workspace_num": ctx.workspace_num,
    }
    repeat_iter_env = os.environ.get("SASE_REPEAT_ITERATION")
    repeat_total_env = os.environ.get("SASE_REPEAT_TOTAL")
    if repeat_iter_env is not None and repeat_total_env is not None:
        try:
            named_args["n"] = int(repeat_iter_env)
            named_args["N"] = int(repeat_total_env)
        except ValueError:
            pass
    if ctx.wait_chats:
        named_args["wait_chats"] = ctx.wait_chats
    vcs_tag = getattr(ctx, "vcs_tag", None)
    if vcs_tag:
        named_args[_WORKFLOW_INHERITED_VCS_TAG_ARG] = vcs_tag
    # ``agents`` is the single reserved Jinja named arg holding every
    # producer's output variables (keyed by agent name). Fail clearly if
    # another context source already provided it.
    output_variable_context = getattr(ctx, "output_variable_namespaces", {}) or {}
    for key, value in output_variable_context.items():
        if key in named_args:
            raise ValueError(
                f"Reserved agent-run Jinja name {key!r} collides with a "
                "built-in workflow argument"
            )
        named_args[key] = value
    return named_args


def _handle_killed_iteration(
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    kill_time = killed_at()
    finalize_pending_tool_calls(
        state.current_artifacts_dir,
        completed_at=kill_time,
    )

    if has_user_kill_intent(state.current_artifacts_dir):
        read_and_delete_marker(state.current_artifacts_dir, ".sase_plan_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_questions_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_monitor_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_gate_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_pipe_pending")
        AGENT_KILLS.labels(reason="user").inc()
        return "killed"

    plan_data = read_and_delete_marker(
        state.current_artifacts_dir,
        ".sase_plan_pending",
    )
    q_data = read_and_delete_marker(
        state.current_artifacts_dir,
        ".sase_questions_pending",
    )
    monitor_data = read_and_delete_marker(
        state.current_artifacts_dir,
        ".sase_monitor_pending",
    )
    gate_data = read_and_delete_marker(
        state.current_artifacts_dir,
        ".sase_gate_pending",
    )
    pipe_data = read_and_delete_marker(
        state.current_artifacts_dir,
        ".sase_pipe_pending",
    )

    if plan_data and _marker_predates_kill(plan_data, kill_time):
        return handle_plan_marker(plan_data, ctx, state)
    if q_data and _marker_predates_kill(q_data, kill_time):
        return handle_questions_marker(q_data, ctx, state)
    if monitor_data and _marker_predates_kill(monitor_data, kill_time):
        return handle_monitor_marker(monitor_data, ctx, state)
    if gate_data and _marker_predates_kill(gate_data, kill_time):
        return handle_gate_marker(gate_data, ctx, state)
    if pipe_data and _marker_predates_kill(pipe_data, kill_time):
        return handle_pipe_marker(pipe_data, ctx, state)

    AGENT_KILLS.labels(reason="user").inc()
    return "killed"


def _marker_predates_kill(
    marker_data: dict[str, Any],
    kill_time: float | None,
) -> bool:
    if kill_time is None:
        return True
    marker_time = marker_data.get("timestamp")
    if not isinstance(marker_time, int | float):
        return True
    return float(marker_time) <= kill_time + 0.001


def run_execution_loop(
    ctx: AgentExecContext,
    prompt: str,
) -> _AgentExecResult:
    """Run the agent workflow loop with retry, plan approval, and question handling."""
    from sase.xprompt.models import create_anonymous_workflow
    from sase.xprompt.workflow_runner import execute_workflow

    _publish_predicted_chat_path(ctx)
    _publish_root_timestamp(ctx)
    if ctx.agent_name:
        os.environ["SASE_AGENT_NAME"] = ctx.agent_name

    from sase.llm_provider.registry import (
        LLM_EXEC_PROVIDER_ENV,
        resolve_execution_provider_name,
    )

    has_execution_provider = bool(
        ctx.agent_llm_provider or os.environ.get(LLM_EXEC_PROVIDER_ENV, "").strip()
    )
    execution_provider = (
        resolve_execution_provider_name(ctx.agent_llm_provider)
        if has_execution_provider
        else None
    )
    tracker = RetryTracker(
        retry_cfg=(
            get_retry_config(execution_provider)
            if execution_provider is not None
            else None
        ),
        attempt_start_epoch=time.time(),
        execution_provider=execution_provider,
    )
    state = LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
        original_agent_timestamp=os.environ.get("SASE_AGENT_TIMESTAMP"),
    )
    result = None

    def _rebind_workspace_identity(output: dict[str, Any], workspace_dir: str) -> None:
        rebind_agent_workspace_identity_from_output(
            ctx,
            artifacts_dir=state.current_artifacts_dir,
            output=output,
            workspace_dir=workspace_dir,
        )

    while True:
        reset_killed()
        _publish_phase_env(state.current_artifacts_dir)
        anon_workflow = create_anonymous_workflow(state.current_prompt)
        if ctx.local_xprompts:
            anon_workflow.xprompts = ctx.local_xprompts

        try:
            result = execute_workflow(
                anon_workflow.name,
                [],
                _build_named_args(ctx),
                artifacts_dir=state.current_artifacts_dir,
                silent=True,
                workflow_obj=anon_workflow,
                project=_resolve_workflow_project(ctx),
                workspace_rebind_callback=_rebind_workspace_identity,
            )
        except Exception as wf_exc:
            if not was_killed():
                action = handle_workflow_error(wf_exc, tracker, ctx, state)
                if action == "continue":
                    continue
                if action == "break":
                    break
                raise
            result = None

        if not was_killed():
            break

        outcome = _handle_killed_iteration(ctx, state)
        if outcome is not None:
            state.loop_outcome = outcome
            break

    return _finalize_loop(ctx, state, tracker, result)
