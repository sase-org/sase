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
from sase.axe.run_agent_helpers import (
    extract_step_output_and_diff_path,
    is_workflow_noop,
    read_and_delete_marker,
    update_meta_field,
)
from sase.axe.run_agent_exec_custom_roles import (
    custom_role_snapshot_from_meta,
    spawn_custom_role_followup,
)
from sase.axe.runner_utils import killed_at, reset_killed, was_killed
from sase.agent.user_kill import has_user_kill_intent
from sase.agent_family import (
    HandoffEvent,
    active_roles_after,
    build_handoff_event,
    evaluate_handoff_event,
    family_state_snapshot,
)
from sase.history.chat import generate_chat_filename, get_chat_file_path
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.retry_config import get_retry_config
from sase.llm_provider._tool_calls import finalize_pending_tool_calls
from sase.plan_approval_choices import filter_roles_by_selected_member_ids
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

    if plan_data and _marker_predates_kill(plan_data, kill_time):
        event = build_handoff_event(
            kind="plan_submitted",
            artifacts_dir=state.current_artifacts_dir,
            payload=plan_data,
            current_role_suffix=state.current_role_suffix,
        )
        return _handle_handoff_event(event, ctx, state)
    if q_data and _marker_predates_kill(q_data, kill_time):
        event = build_handoff_event(
            kind="questions_submitted",
            artifacts_dir=state.current_artifacts_dir,
            payload=q_data,
            current_role_suffix=state.current_role_suffix,
        )
        return _handle_handoff_event(event, ctx, state)

    AGENT_KILLS.labels(reason="user").inc()
    return "killed"


def _handle_handoff_event(
    event: HandoffEvent,
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    if event.kind == "plan_submitted":
        return handle_plan_marker(event, ctx, state)
    if event.kind == "questions_submitted":
        return handle_questions_marker(event, ctx, state)
    return None


def _current_agent_family_role(artifacts_dir: str) -> str | None:
    import json

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    role = meta.get("agent_family_role")
    return role if isinstance(role, str) and role else None


def _handle_completed_followup(ctx: AgentExecContext, state: LoopState) -> bool:
    """Return True when a normally completed phase should finish the loop."""

    if state.agent_step <= 1 or not state.current_role_suffix:
        return True

    family_role = _current_agent_family_role(state.current_artifacts_dir)
    event = build_handoff_event(
        kind="role_completed",
        artifacts_dir=state.current_artifacts_dir,
        payload={
            "outcome": "success",
            "artifacts_ref": state.current_artifacts_dir,
        },
        current_role_suffix=state.current_role_suffix,
        agent_family_role=family_role,
    )
    active_custom_roles = filter_roles_by_selected_member_ids(
        active_roles_after(event.interrupted_role, project=ctx.project_name),
        state.selected_member_ids,
    )
    evaluation = evaluate_handoff_event(
        event,
        family_state_snapshot(
            current_role_suffix=state.current_role_suffix,
            feedback_bullets=state.feedback_bullets,
            qa_round_count=len(state.qa_rounds),
            saved_chat_suffixes=tuple(
                suffix for suffix, _path in state.saved_chat_paths if suffix
            ),
            agent_family_role=event.interrupted_role,
            visit_counts=state.custom_role_visit_counts,
        ),
        custom_roles=active_custom_roles,
        custom_role_snapshot=custom_role_snapshot_from_meta(
            state.current_artifacts_dir
        ),
    )
    if evaluation.custom_role is not None and not evaluation.terminal:
        spawn_custom_role_followup(
            evaluation.custom_role,
            ctx,
            state,
            source_artifacts=state.current_artifacts_dir,
            outcome=str(event.payload.get("outcome") or "success"),
            source_role=event.interrupted_role,
        )
        return False
    if evaluation.custom_role is not None and evaluation.terminal_reason:
        update_meta_field(
            state.current_artifacts_dir,
            "custom_role_terminal_reason",
            evaluation.terminal_reason,
        )
        update_meta_field(
            state.current_artifacts_dir,
            "custom_role_terminal_role",
            evaluation.custom_role.role.id,
        )
    return evaluation.terminal


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
        original_agent_timestamp=os.environ.get("SASE_AGENT_TIMESTAMP"),
    )
    result = None

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
            if not _handle_completed_followup(ctx, state):
                continue
            break

        outcome = _handle_killed_iteration(ctx, state)
        if outcome is not None:
            state.loop_outcome = outcome
            break

    return _finalize_loop(ctx, state, tracker, result)
