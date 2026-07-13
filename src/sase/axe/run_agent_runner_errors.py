"""Error marker helpers for ``run_agent_runner``."""

import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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


def record_runner_error(
    exc: BaseException,
    *,
    context: RunnerErrorContext,
    write_error_done_marker: Callable[..., Any],
    agent_kills: Any,
    message_prefix: str,
    error_summary: str | None = None,
) -> tuple[str, str]:
    """Print the active exception and write a failed ``done.json`` marker."""
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
    )
    return summary, traceback_str
