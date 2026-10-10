"""Error marker helpers for ``run_agent_runner``."""

import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.axe.runner_auto_restart_doorbell import (
    drop_doorbell,
    pending_recovery_payload,
)
from sase.axe.runner_failure_facts import (
    capture_failure_facts,
    facts_look_like_update_skew,
)
from sase.axe.runner_lifecycle_phase import current_lifecycle_phase
from sase.axe.source_skew import code_swap_explanation
from sase.llm_provider.retry_config import find_retry_config_for_error


@dataclass(frozen=True)
class RunnerErrorContext:
    current_artifacts_dir: str
    cl_name: str
    project_file: str
    timestamp: str
    artifacts_timestamp: str
    workspace_num: int
    workspace_dir: str
    output_path: str
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_vcs_provider: str | None
    agent_hidden: bool
    project_name: str | None = None


def record_runner_error(
    exc: BaseException,
    *,
    context: RunnerErrorContext,
    write_error_done_marker: Callable[..., Any],
    agent_kills: Any,
    message_prefix: str,
    error_summary: str | None = None,
    auto_restart_enabled: bool = False,
    killed: bool = False,
) -> tuple[str, str]:
    """Print the active exception and write a failed ``done.json`` marker.

    When the auto-restart feature is enabled and the failure facts look
    like update skew, the marker carries ``recovery.state == "pending"``
    and a doorbell file is dropped for the scheduler job — before any
    completion notification is sent. No doorbell is dropped for user
    kills. The doorbell path uses only boot-imported modules, so a torn
    interpreter can still ring it.
    """
    print(f"{message_prefix}: {exc}", file=sys.stderr)
    traceback.print_exc()
    summary = error_summary or f"{type(exc).__qualname__}: {exc}"
    traceback_str = traceback.format_exc()
    if find_retry_config_for_error(summary) is not None:
        print(
            "This runner failure is retryable; retry/relaunch the agent to use "
            "a fresh process.",
            file=sys.stderr,
        )
    swap_explanation = code_swap_explanation(exc)
    if swap_explanation is not None:
        print(
            f"Likely cause: {swap_explanation}.",
            file=sys.stderr,
        )
    failure_facts = capture_failure_facts(exc, phase=current_lifecycle_phase())
    recovery: dict[str, Any] | None = None
    if (
        auto_restart_enabled
        and not killed
        and facts_look_like_update_skew(failure_facts)
    ):
        recovery = pending_recovery_payload()
    agent_kills.labels(reason="error").inc()
    write_error_done_marker(
        current_artifacts_dir=context.current_artifacts_dir,
        cl_name=context.cl_name,
        project_file=context.project_file,
        timestamp=context.timestamp,
        artifacts_timestamp=context.artifacts_timestamp,
        workspace_num=context.workspace_num,
        workspace_dir=context.workspace_dir,
        output_path=context.output_path,
        agent_name=context.agent_name,
        agent_model=context.agent_model,
        agent_llm_provider=context.agent_llm_provider,
        agent_vcs_provider=context.agent_vcs_provider,
        agent_hidden=context.agent_hidden,
        error=summary,
        traceback_str=traceback_str,
        failure_facts=failure_facts,
        recovery=recovery,
    )
    if recovery is not None:
        # The done marker is durable now; ring before the completion
        # notification so a broken notify path cannot lose the recovery.
        drop_doorbell(
            artifacts_dir=context.current_artifacts_dir,
            project=context.project_name or "project",
            agent_name=context.agent_name,
            skew_suspect=True,
        )
    return summary, traceback_str
