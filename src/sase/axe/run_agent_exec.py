"""Agent execution loop for the run agent runner."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.axe.run_agent_exec_finalize import finalize_loop as _finalize_loop
from sase.axe.run_agent_exec_markers import (
    publish_phase_env as _publish_phase_env,
    write_done_marker_and_update_index as _write_done_marker_and_update_index,
)
from sase.axe.run_agent_exec_staged import (
    StagedInlineContinuation,
    dispatch_completed_staged_handoff,
)
from sase.axe.run_agent_exec_staged_monitor import cleanup_staged_monitor_handoff
from sase.axe.run_agent_exec_plan_artifacts import (
    get_embedded_workflow_refs as _get_embedded_workflow_refs,
)
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_exec_types import (
    AgentExecContext,
    AgentExecResult as _AgentExecResult,
    LoopState,
)
from sase.axe.run_agent_workspace_identity import (
    rebind_agent_workspace_identity_from_output,
)
from sase.agent.staged_handoff import discard_staged_handoff
from sase.axe.run_agent_helpers import (
    extract_step_output_and_diff_path,
    is_workflow_noop,
    read_and_delete_marker,
)
from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
from sase.axe.runner_signals import killed_at, reset_killed, was_killed
from sase.axe.runner_kill_provenance import record_kill_provenance
from sase.agent.user_kill import has_hijack_intent, has_user_kill_intent
from sase.history.chat import generate_chat_filename, get_chat_file_path
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.retry_config import get_retry_config
from sase.llm_provider._tool_calls import finalize_pending_tool_calls

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
    """Return project scope for macro/workflow resolution."""
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
    from sase.macro.workflow_runner import _WORKFLOW_INHERITED_VCS_TAG_ARG

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


def _build_wait_namespace(ctx: AgentExecContext) -> Any:
    from sase.axe.run_agent_refs import (
        WaitDependencyResolution,
        WaitRuntimeNamespace,
    )

    resolution = getattr(ctx, "wait_context", None)
    if not isinstance(resolution, WaitDependencyResolution):
        resolution = WaitDependencyResolution.from_chats(
            list(getattr(ctx, "wait_chats", []) or [])
        )
    return WaitRuntimeNamespace(resolution)


def _handle_killed_iteration(
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    del ctx
    kill_time = killed_at()
    finalize_pending_tool_calls(
        state.current_artifacts_dir,
        completed_at=kill_time,
    )

    if has_user_kill_intent(state.current_artifacts_dir):
        cleanup_staged_monitor_handoff(state.current_artifacts_dir, held=False)
        discard_staged_handoff(state.current_artifacts_dir)
        read_and_delete_marker(state.current_artifacts_dir, ".sase_plan_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_questions_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_monitor_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_gate_pending")
        read_and_delete_marker(state.current_artifacts_dir, ".sase_pipe_pending")
        record_kill_provenance(state.current_artifacts_dir, state, kill_time=kill_time)
        if has_hijack_intent(state.current_artifacts_dir):
            return "hijacked"
        return "killed"

    # External teardown (OOM, a manual kill, a host stop). Staged records
    # stay on disk for the later reconciler and are never adopted as a
    # successful handoff here. Leftover pending markers are archived
    # evidence only.
    record_kill_provenance(state.current_artifacts_dir, state, kill_time=kill_time)
    return "killed"


def _dispatch_staged_on_workflow_error(
    ctx: AgentExecContext,
    state: LoopState,
) -> bool:
    """Finalize a staged turn after a workflow/provider error.

    Returns ``True`` when a staged record (or malformed staged state)
    governed this turn: the caller must end the loop with a failed outcome
    instead of retrying ordinary work or re-raising. Returns ``False`` when
    no staged state exists and normal retry handling should proceed.
    """
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_staged_handoff,
        )

        try:
            staged = read_staged_handoff(state.current_artifacts_dir)
        except StagedHandoffError:
            staged = {"staged_id": "malformed"}
        if staged is None:
            return False
    except Exception:  # noqa: BLE001 - staged detection fails open to retry.
        return False
    try:
        staged_dispatch = dispatch_completed_staged_handoff(
            state.current_artifacts_dir,
            StagedInlineContinuation(ctx=ctx, state=state),
        )
    except Exception:  # noqa: BLE001 - held receipt already records the cause.
        logging.getLogger(__name__).exception(
            "staged handoff %s adoption failed after workflow error",
            state.current_artifacts_dir,
        )
        state.loop_outcome = "failed"
        return True
    if staged_dispatch is None:
        return False
    if not staged_dispatch.adopted:
        logging.getLogger(__name__).error(
            "staged handoff %s held after workflow error: %s",
            state.current_artifacts_dir,
            staged_dispatch.reason,
        )
        state.loop_outcome = "failed"
        return True
    if staged_dispatch.outcome is None:
        # An inline continuation cannot safely resume after the ordinary
        # task itself failed; hold the turn as failed instead of retrying.
        logging.getLogger(__name__).error(
            "staged handoff %s adopted without a terminal outcome "
            "after workflow error; holding as failed",
            state.current_artifacts_dir,
        )
        state.loop_outcome = "failed"
        return True
    state.loop_outcome = staged_dispatch.outcome
    return True


def _export_exec_agent_tab(
    ctx: AgentExecContext,
    export: Callable[[str | None], None],
) -> None:
    """Export ``SASE_AGENT_TAB`` for the execution loop's own resolved tab."""
    meta = ctx.agent_meta if isinstance(ctx.agent_meta, dict) else {}
    tab = meta.get("agent_tab")
    export(tab if isinstance(tab, str) and tab else None)


def run_execution_loop(
    ctx: AgentExecContext,
    prompt: str,
) -> _AgentExecResult:
    """Run the agent workflow loop with retry, plan approval, and question handling."""
    from sase.axe.run_agent_successor import (
        mark_detached_successor_started_from_environment,
    )

    mark_detached_successor_started_from_environment()
    mark_lifecycle_phase(ctx.artifacts_dir, "provider_running")
    from sase.macro.runtime_context import bind_runtime_template_vars

    with bind_runtime_template_vars({"wait": _build_wait_namespace(ctx)}):
        return _run_execution_loop_bound(ctx, prompt)


def _run_execution_loop_bound(
    ctx: AgentExecContext,
    prompt: str,
) -> _AgentExecResult:
    from sase.macro.models import create_anonymous_workflow
    from sase.macro.workflow_runner import execute_workflow

    _publish_predicted_chat_path(ctx)
    _publish_root_timestamp(ctx)
    if ctx.agent_name:
        os.environ["SASE_AGENT_NAME"] = ctx.agent_name
    from sase.axe.run_agent_directive_metadata import export_agent_tab_env

    _export_exec_agent_tab(ctx, export_agent_tab_env)

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
        authored_local_request=ctx.authored_local_request or prompt,
        initial_authored_local_request=ctx.authored_local_request or prompt,
        continuation_segments=ctx.launch_continuation_segments,
        original_agent_timestamp=os.environ.get("SASE_AGENT_TIMESTAMP"),
    )
    from sase.continuation_capture import persist_workspace_facts_best_effort

    state.continuation_workspace_ref = persist_workspace_facts_best_effort(ctx, state)
    result = None

    def _rebind_workspace_identity(output: dict[str, Any], workspace_dir: str) -> None:
        rebind_agent_workspace_identity_from_output(
            ctx,
            artifacts_dir=state.current_artifacts_dir,
            output=output,
            workspace_dir=workspace_dir,
        )

    turn_index = 0
    while True:
        turn_index += 1
        if turn_index > 1:
            # No provider is running at this point; reap what the previous
            # turn leaked so it cannot spin through this turn.
            try:
                from sase.agent.scope_sweep import sweep_own_agent_scope

                sweep_own_agent_scope(context="turn")
            except Exception:  # noqa: BLE001 - the sweep must never break a turn.
                logging.getLogger(__name__).exception(
                    "Agent scope sweep between turns failed"
                )
        reset_killed()
        _publish_phase_env(state.current_artifacts_dir)
        anon_workflow = create_anonymous_workflow(state.current_prompt)
        if ctx.local_macros:
            anon_workflow.macros = ctx.local_macros

        pending_successor = state.pending_staged_successor
        if pending_successor is not None:
            from sase.axe.run_agent_successor import mark_staged_successor_started

            if not mark_staged_successor_started(
                pending_successor["origin_artifacts_dir"],
                pending_successor["staged_id"],
            ):
                raise RuntimeError("staged pipe successor identity disappeared")
            state.pending_staged_successor = None

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
                authored_local_request=state.authored_local_request,
                continuation_segments=state.continuation_segments,
            )
            state.continuation_prepared_ref = getattr(
                result,
                "continuation_prepared_ref",
                None,
            )
        except Exception as wf_exc:
            if not was_killed():
                if _dispatch_staged_on_workflow_error(ctx, state):
                    break
                action = handle_workflow_error(wf_exc, tracker, ctx, state)
                if action == "continue":
                    continue
                if action == "break":
                    break
                raise
            result = None

        if not was_killed():
            staged_dispatch = dispatch_completed_staged_handoff(
                state.current_artifacts_dir,
                StagedInlineContinuation(ctx=ctx, state=state),
            )
            if staged_dispatch is not None:
                if not staged_dispatch.adopted:
                    logging.getLogger(__name__).error(
                        "staged handoff %s held: %s",
                        state.current_artifacts_dir,
                        staged_dispatch.reason,
                    )
                    state.loop_outcome = "failed"
                    break
                if staged_dispatch.outcome is None:
                    # Plan feedback and synchronous auto-approval can hand
                    # control to the next prompt without ending the loop.
                    continue
                state.loop_outcome = staged_dispatch.outcome
            break

        outcome = _handle_killed_iteration(ctx, state)
        if outcome is not None:
            state.loop_outcome = outcome
            break

    return _finalize_loop(ctx, state, tracker, result)
