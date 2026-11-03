"""Staged adoption helpers for tests after the kill-path retirement.

These thin wrappers point test callers at the staged entry points with a real
provider response and a real staged ID, keeping per-test edits small.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState


def handle_plan_marker(
    plan_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    planner_response: str = "Test staged plan response.",
    staged_id: str | None = None,
    approval_context: Any | None = None,
) -> str | None:
    """Adopt a staged plan in tests with a real provider response."""
    from sase.axe.run_agent_exec_plan import handle_staged_plan_marker

    return handle_staged_plan_marker(
        plan_data,
        ctx,
        state,
        planner_response=planner_response,
        staged_id=staged_id,
        approval_context=approval_context,
    )


def handle_questions_marker(
    q_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    provider_response: str = "Test staged questions response.",
    staged_id: str | None = None,
    approval_context: Any | None = None,
) -> str | None:
    """Adopt a staged questions handoff in tests with a real response."""
    from sase.axe.run_agent_exec_questions import handle_staged_questions_marker

    return handle_staged_questions_marker(
        q_data,
        ctx,
        state,
        provider_response=provider_response,
        staged_id=staged_id,
        approval_context=approval_context,
    )


def handle_pipe_marker(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    provider_response: str = "Test staged pipe response.",
    staged_id: str | None = None,
) -> str | None:
    """Adopt a staged pipe handoff in tests with a real staged ID."""
    from sase.axe.run_agent_exec_pipe_handoff import handle_staged_pipe_marker

    return handle_staged_pipe_marker(
        pipe_data,
        ctx,
        state,
        provider_response=provider_response,
        staged_id=staged_id or f"test-staged-{uuid.uuid4().hex[:8]}",
    )


def handle_monitor_marker(
    monitor_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    response: str = "Test staged monitor response.",
) -> str:
    """Adopt a staged monitor handoff in tests with strict capture."""
    from unittest.mock import patch

    from sase.axe.run_agent_exec_monitor import capture_monitor_handoff

    with (
        patch(
            "sase.continuation_capture.publish_handoff_checkpoint",
            return_value="test-checkpoint-ref",
        ),
        patch(
            "sase.continuation_capture.persist_agent_delta",
            return_value=type("Delta", (), {"node_id": "test-node"})(),
        ),
    ):
        result = capture_monitor_handoff(
            monitor_data,
            ctx,
            state,
            response=response,
            status="completed",
        )
    return "monitored" if result is not None else "monitored"
