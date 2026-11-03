"""Test helpers for leftover pending-marker adoption after kill-path retirement."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState


def handle_plan_marker(
    plan_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Adopt a leftover ``.sase_plan_pending`` marker for tests."""
    from sase.axe.run_agent_exec_plan import _handle_plan_handoff

    return _handle_plan_handoff(
        plan_data,
        ctx,
        state,
        planner_response=None,
        interrupted=True,
    )


def handle_questions_marker(
    q_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Adopt a leftover ``.sase_questions_pending`` marker for tests."""
    from sase.axe.run_agent_exec_questions import _handle_questions_handoff

    return _handle_questions_handoff(
        q_data,
        ctx,
        state,
        provider_response=None,
        interrupted=True,
    )


def handle_pipe_marker(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Adopt a leftover ``.sase_pipe_pending`` marker for tests."""
    from sase.axe.run_agent_exec_pipe_handoff import _handle_pipe_handoff

    return _handle_pipe_handoff(
        pipe_data,
        ctx,
        state,
        provider_response=None,
        interrupted=True,
    )


def handle_monitor_marker(
    monitor_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str:
    """Adopt a leftover ``.sase_monitor_pending`` marker for tests."""
    from sase.axe.run_agent_exec_monitor import (
        _format_monitor_response,
        _monitor_member_meta,
        _text,
        capture_monitor_handoff,
    )
    from sase.axe.run_agent_helpers import (
        finalize_handoff_artifacts_as_completed,
        normalize_handoff_interruption_state,
    )

    normalize_handoff_interruption_state(state.current_artifacts_dir)
    finalize_handoff_artifacts_as_completed(state.current_artifacts_dir)
    monitor_meta = _monitor_member_meta(monitor_data)
    monitor_id = _text(monitor_data.get("monitor_id")) or _text(
        monitor_meta.get("monitor_id")
    )
    member_agent_name = _text(monitor_data.get("member_agent_name")) or _text(
        monitor_meta.get("name")
    )
    response = _format_monitor_response(
        monitor_id=monitor_id,
        member_agent_name=member_agent_name,
        command=_text(monitor_meta.get("monitor_command")),
        cwd=_text(monitor_meta.get("monitor_cwd")),
        reason=_text(monitor_meta.get("monitor_reason")),
        next_action=_text(monitor_meta.get("monitor_next_action")),
    )
    capture_monitor_handoff(
        monitor_data,
        ctx,
        state,
        response=response,
        status="interrupted",
        reset_killed_state=True,
    )
    return "monitored"
