"""Retry and error handling for the agent execution loop."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.axe.run_agent_exec_attempts import snapshot_attempt
from sase.axe.run_agent_helpers import append_meta_list_field
from sase.axe.runner_signals import was_killed
from sase.axe.runner_workspace import prepare_workspace
from sase.llm_provider.provider_disable import get_active_provider_disable
from sase.telemetry.metrics import LLM_RETRIES
from sase.llm_provider.retry_config import (
    ProviderRetryConfig,
    RetryState,
    find_retry_config_for_error,
    get_wait_time,
    is_retryable_error,
    truncate_error_snippet,
)
from sase.llm_provider.usage_limit_config import (
    UsageLimitDetection,
    detect_usage_limit,
    find_usage_limit_detection_for_error,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)

_RetryAction = Literal["continue", "break", "raise"]


@dataclass
class RetryTracker:
    """Mutable retry state across loop iterations."""

    retry_cfg: ProviderRetryConfig | None
    retry_errors: list[str] = field(default_factory=list)
    retry_count: int = 0
    using_fallback: bool = False
    attempt_start_epoch: float = field(default_factory=time.time)
    # The provider resolved to actually execute the agent's LLM calls (after
    # load-balancing / SASE_LLM_EXEC_PROVIDER override), used to scope
    # usage-limit detection to the provider that ran. None when the caller
    # never resolved one (e.g. no provider requested and no override set).
    execution_provider: str | None = None


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


def _resolve_fallback_provider(fallback_model: str | None) -> str | None:
    """Return the provider a configured ``fallback_model`` resolves to, if any."""
    if not fallback_model:
        return None
    from sase.llm_provider.registry import resolve_model_provider

    try:
        provider, _ = resolve_model_provider(fallback_model)
    except Exception:
        return None
    return provider


def _read_recorded_execution_provider(artifacts_dir: str | None) -> str | None:
    """Return the ``exec_llm_provider`` written for the attempt that just ran."""
    if not artifacts_dir:
        return None
    try:
        payload = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    recorded = payload.get("exec_llm_provider")
    if isinstance(recorded, str) and recorded.strip():
        return recorded
    return None


def _refresh_execution_provider(
    tracker: RetryTracker, artifacts_dir: str | None
) -> str | None:
    """Pin usage-limit attribution to the provider that just executed.

    ``_invoke.py`` records the authoritative ``exec_llm_provider`` before each
    subprocess, including after a fallback switches models. The loop-start
    provider is only a fallback for workflows that never wrote one.
    """
    recorded = _read_recorded_execution_provider(artifacts_dir)
    if recorded is not None:
        tracker.execution_provider = recorded
    return tracker.execution_provider


def _detect_usage_limit_for_error(
    error_str: str, execution_provider: str | None
) -> UsageLimitDetection | None:
    """Detect a usage-limit match for the provider that actually ran.

    When that provider is known, only its config is consulted — quoted
    another-provider limit prose must not change retry policy. Scanning
    every configured provider is reserved for workflows that genuinely
    lack execution-provider provenance.
    """
    if execution_provider:
        return detect_usage_limit(execution_provider, error_str)
    return find_usage_limit_detection_for_error(error_str)


def _usage_limit_retry_precedence(
    error_str: str,
    tracker: RetryTracker,
    active_retry_cfg: ProviderRetryConfig,
) -> tuple[UsageLimitDetection | None, bool]:
    """Return ``(detection, fallback_blocked)`` for a possible usage-limit error.

    A usage-limit match means the wait-and-retry branch must never run for
    the provider that hit it — sleeping through a retry window helps nobody
    when the provider itself just reported it is out of quota.
    ``fallback_blocked`` reports whether the configured fallback is also
    unusable (none configured, already used, or it resolves to the same
    now-disabled provider), in which case the caller must raise immediately.

    Detection failures fail open (returns ``(None, False)``) so a bug in
    this subsystem can never block an otherwise-healthy retry.
    """
    try:
        detection = _detect_usage_limit_for_error(error_str, tracker.execution_provider)
        if detection is None:
            return None, False
        fallback_provider = _resolve_fallback_provider(active_retry_cfg.fallback_model)
        fallback_ok = (
            bool(active_retry_cfg.fallback_model)
            and not tracker.using_fallback
            and fallback_provider is not None
            and fallback_provider != detection.provider
            and get_active_provider_disable(fallback_provider) is None
        )
        return detection, not fallback_ok
    except Exception:
        logger.debug(
            "usage-limit retry precedence check failed; retrying normally",
            exc_info=True,
        )
        return None, False


def _usage_limit_skip_reason(detection: UsageLimitDetection) -> str:
    return (
        f"usage limit: {detection.provider} hit its usage limit and was "
        "disabled; retry skipped instead of waiting through a futile window"
    )


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
    _refresh_execution_provider(
        tracker, state.current_artifacts_dir or ctx.artifacts_dir
    )

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

    def _snapshot(
        status: Literal["failed", "raised"], *, reason: str | None = None
    ) -> None:
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
            reason=reason,
        )

    # A usage-limit failure takes precedence over ordinary retry
    # classification: even if the error also matches a configured retry
    # pattern (e.g. codex's "rate limit" / "429" patterns), sleeping
    # through wait_times to re-hit an account-wide usage limit only holds
    # the workspace claim hostage for no benefit.
    usage_limit_detection, fallback_blocked_by_usage_limit = (
        _usage_limit_retry_precedence(error_str, tracker, active_retry_cfg)
    )

    can_wait_and_retry = (
        usage_limit_detection is None
        and tracker.retry_count < active_retry_cfg.max_retries
    )
    if can_wait_and_retry:
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
        # (as if `sase run` had been invoked).  The child inherits the
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
                    agent_name=ctx.agent_name,
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
        os.environ["SASE_ACTIVE_PROJECT_DIR"] = ctx.workspace_dir
        from sase.sdd.env import set_sdd_dir_env

        set_sdd_dir_env(
            os.environ,
            workspace_dir=ctx.workspace_dir,
            workspace_num=ctx.workspace_num,
        )
        tracker.attempt_start_epoch = time.time()
        return "continue"

    elif (
        active_retry_cfg.fallback_model
        and not tracker.using_fallback
        and not fallback_blocked_by_usage_limit
    ):
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
        os.environ["SASE_ACTIVE_PROJECT_DIR"] = ctx.workspace_dir
        from sase.sdd.env import set_sdd_dir_env

        set_sdd_dir_env(
            os.environ,
            workspace_dir=ctx.workspace_dir,
            workspace_num=ctx.workspace_num,
        )
        tracker.attempt_start_epoch = time.time()
        return "continue"

    if usage_limit_detection is not None:
        _snapshot("raised", reason=_usage_limit_skip_reason(usage_limit_detection))
    else:
        _snapshot("raised")
    return "raise"
