"""Retry and error handling for the agent execution loop."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from sase.axe.runner_utils import prepare_workspace, was_killed
from sase.llm_provider.retry_config import (
    ProviderRetryConfig,
    RetryState,
    find_retry_config_for_error,
    get_wait_time,
    is_retryable_error,
    truncate_error_snippet,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

_RetryAction = Literal["continue", "break", "raise"]


@dataclass
class RetryTracker:
    """Mutable retry state across loop iterations."""

    retry_cfg: ProviderRetryConfig | None
    retry_errors: list[str] = field(default_factory=list)
    retry_count: int = 0
    using_fallback: bool = False


def handle_workflow_error(
    exc: Exception,
    tracker: RetryTracker,
    ctx: AgentExecContext,
    state: LoopState,
) -> _RetryAction:
    """Handle a workflow execution error with retry/fallback logic.

    Returns ``"continue"`` to retry, ``"break"`` if killed during wait,
    or ``"raise"`` to propagate the exception.
    """
    error_str = str(exc)

    # Try the agent's own provider config first; fall back to
    # checking all configured providers (handles the case where
    # an inner workflow step uses a different LLM provider than
    # the outer workflow).
    active_retry_cfg = tracker.retry_cfg
    if not (active_retry_cfg and is_retryable_error(error_str, active_retry_cfg)):
        active_retry_cfg = find_retry_config_for_error(error_str)

    if not (state.allow_retry and active_retry_cfg):
        return "raise"

    # Promote to retry_cfg so subsequent iterations use it
    tracker.retry_cfg = active_retry_cfg
    snippet = truncate_error_snippet(error_str)
    tracker.retry_errors.append(snippet)

    if tracker.retry_count < active_retry_cfg.max_retries:
        # Retry with wait
        tracker.retry_count += 1
        wait_time = get_wait_time(tracker.retry_count, active_retry_cfg)
        RetryState(
            status="retrying",
            retry_count=tracker.retry_count,
            max_retries=active_retry_cfg.max_retries,
            wait_seconds=wait_time,
            next_retry_at_epoch=time.time() + wait_time,
            last_error_snippet=snippet,
        ).write_to(ctx.artifacts_dir)

        from sase.notifications.senders import notify_agent_retry

        notify_agent_retry(
            "agent-retry",
            ctx.cl_name,
            tracker.retry_count,
            active_retry_cfg.max_retries,
            wait_time,
            snippet,
        )

        # Sleep in 1s increments
        for _ in range(wait_time):
            if was_killed():
                break
            time.sleep(1)
        if was_killed():
            state.loop_outcome = "killed"
            return "break"

        # Re-prepare workspace
        RetryState(
            status="running_retry",
            retry_count=tracker.retry_count,
            max_retries=active_retry_cfg.max_retries,
            last_error_snippet=snippet,
        ).write_to(ctx.artifacts_dir)
        if ctx.update_target and not ctx.is_home_mode:
            prepare_workspace(
                ctx.workspace_dir,
                ctx.cl_name,
                ctx.update_target,
                backup_suffix="ace",
                project_basename=ctx.project_name,
            )
        os.chdir(ctx.workspace_dir)
        return "continue"

    elif active_retry_cfg.fallback_model and not tracker.using_fallback:
        # Fallback to alternate model
        tracker.using_fallback = True
        os.environ["SASE_MODEL_OVERRIDE"] = active_retry_cfg.fallback_model
        RetryState(
            status="running_fallback",
            retry_count=tracker.retry_count,
            max_retries=active_retry_cfg.max_retries,
            fallback_model=active_retry_cfg.fallback_model,
            using_fallback=True,
            last_error_snippet=snippet,
        ).write_to(ctx.artifacts_dir)

        from sase.notifications.senders import notify_agent_fallback

        notify_agent_fallback(
            "agent-retry",
            ctx.cl_name,
            active_retry_cfg.fallback_model,
            tracker.retry_count,
        )

        if ctx.update_target and not ctx.is_home_mode:
            prepare_workspace(
                ctx.workspace_dir,
                ctx.cl_name,
                ctx.update_target,
                backup_suffix="ace",
                project_basename=ctx.project_name,
            )
        os.chdir(ctx.workspace_dir)
        return "continue"

    return "raise"
