"""Retry and error handling for the agent execution loop."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sase.axe.run_agent_exec_attempts import snapshot_attempt
from sase.axe.run_agent_helpers import append_meta_list_field
from sase.axe.runner_utils import prepare_workspace, was_killed
from sase.telemetry.metrics import LLM_RETRIES
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
    attempt_start_epoch: float = field(default_factory=time.time)


def _maybe_prepend_continuation(state: LoopState, cfg: ProviderRetryConfig) -> None:
    """Prepend the retry continuation nudge to the current prompt if set.

    Idempotent: if the nudge is already at the head of the prompt, it is
    not re-applied (guards against compounding across multiple retries).
    """
    nudge = cfg.continuation_prompt
    if not nudge or not state.current_prompt:
        return
    if state.current_prompt.startswith(nudge):
        return
    state.current_prompt = f"{nudge}\n\n{state.current_prompt}"


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

    if not active_retry_cfg:
        return "raise"

    # Promote to retry_cfg so subsequent iterations use it
    tracker.retry_cfg = active_retry_cfg
    snippet = truncate_error_snippet(error_str)
    tracker.retry_errors.append(snippet)

    # The attempt that just failed is always attempt (retry_count + 1).
    attempt_number_of_failed = tracker.retry_count + 1
    attempt_end_epoch = time.time()

    def _snapshot(status: Literal["failed", "raised"]) -> None:
        snapshot_attempt(
            state.current_artifacts_dir or ctx.artifacts_dir,
            attempt_number_of_failed,
            status=status,
            start_epoch=tracker.attempt_start_epoch,
            end_epoch=attempt_end_epoch,
            error_full=error_str,
            error_snippet=snippet,
            model=ctx.agent_model,
            used_fallback=tracker.using_fallback,
        )

    if tracker.retry_count < active_retry_cfg.max_retries:
        _snapshot("failed")
        # Retry with wait
        tracker.retry_count += 1
        LLM_RETRIES.labels(provider=ctx.agent_llm_provider or "unknown").inc()
        _maybe_prepend_continuation(state, active_retry_cfg)
        wait_time = get_wait_time(tracker.retry_count, active_retry_cfg)
        RetryState(
            status="retrying",
            retry_count=tracker.retry_count,
            max_retries=active_retry_cfg.max_retries,
            wait_seconds=wait_time,
            next_retry_at_epoch=time.time() + wait_time,
            last_error_snippet=snippet,
        ).write_to(ctx.artifacts_dir)

        # Sleep in 1s increments
        for _ in range(wait_time):
            if was_killed():
                break
            time.sleep(1)
        if was_killed():
            state.loop_outcome = "killed"
            return "break"

        # ----------------------------------------------------------------
        # Spawn-on-retry path (opt-in via ProviderRetryConfig.spawn_new_agent)
        # ----------------------------------------------------------------
        # When the active provider's retry config sets spawn_new_agent=True,
        # we replace the in-process retry with a fresh detached child agent
        # (as if `sase run -d` had been invoked).  The child inherits the
        # workspace claim, chat history, plan path, and continuation nudge
        # via retry_handoff.json.  On spawn-side failure we fall back to
        # the legacy in-process retry path so the user is never worse off.
        if active_retry_cfg.spawn_new_agent and not ctx.is_home_mode:
            from sase.axe.run_agent_retry_spawn import (
                mark_parent_retried,
                spawn_retry_agent,
            )

            spawn_result = spawn_retry_agent(
                ctx=ctx,
                state=state,
                tracker=tracker,
                error_snippet=snippet,
                continuation_prompt=active_retry_cfg.continuation_prompt,
            )
            if spawn_result is not None:
                mark_parent_retried(
                    artifacts_dir=ctx.artifacts_dir,
                    child_artifacts_timestamp=spawn_result["child_artifacts_timestamp"],
                    chain_root_timestamp=spawn_result["chain_root_timestamp"],
                    handoff_path=spawn_result["handoff_path"],
                    error_category=spawn_result["error_category"],
                )
                # Mark the loop outcome as retried-and-handed-off so the
                # parent runner exits cleanly with FAILED status, leaving
                # the child to carry the work forward.
                state.loop_outcome = "failed_retried"
                return "break"
            # Spawn failed — fall through to the in-process retry path.

        # Re-prepare workspace
        RetryState(
            status="running_retry",
            retry_count=tracker.retry_count,
            max_retries=active_retry_cfg.max_retries,
            last_error_snippet=snippet,
        ).write_to(ctx.artifacts_dir)
        append_meta_list_field(
            ctx.artifacts_dir,
            "retry_started_at",
            datetime.now(UTC).isoformat(),
        )
        if (
            ctx.update_target
            and not ctx.is_home_mode
            and not active_retry_cfg.preserve_workspace
        ):
            prepare_workspace(
                ctx.workspace_dir,
                ctx.cl_name,
                ctx.update_target,
                backup_suffix="ace",
                project_basename=ctx.project_name,
            )
        os.chdir(ctx.workspace_dir)
        tracker.attempt_start_epoch = time.time()
        return "continue"

    elif active_retry_cfg.fallback_model and not tracker.using_fallback:
        _snapshot("failed")
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
        append_meta_list_field(
            ctx.artifacts_dir,
            "retry_started_at",
            datetime.now(UTC).isoformat(),
        )

        if (
            ctx.update_target
            and not ctx.is_home_mode
            and not active_retry_cfg.preserve_workspace
        ):
            prepare_workspace(
                ctx.workspace_dir,
                ctx.cl_name,
                ctx.update_target,
                backup_suffix="ace",
                project_basename=ctx.project_name,
            )
        os.chdir(ctx.workspace_dir)
        tracker.attempt_start_epoch = time.time()
        return "continue"

    _snapshot("raised")
    return "raise"
