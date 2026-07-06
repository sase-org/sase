"""Shutdown and completion helpers for ``run_agent_runner``."""

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)


@dataclass(frozen=True)
class RunnerShutdownContext:
    project_file: str
    workflow_name: str
    cl_name: str
    artifacts_timestamp: str
    artifacts_dir: str
    output_path: str
    submitted_xprompt: str
    prompt: str
    is_home_mode: bool


@dataclass
class RunnerShutdownState:
    success: bool
    duration: str
    workspace_num: int
    workspace_dir: str
    current_artifacts_dir: str
    running_marker_path: str | None
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_hidden: bool
    saved_path: str | None
    diff_path: str | None
    markdown_pdf_paths: list[str]
    markdown_source_count: int
    image_paths: list[str]
    video_paths: list[str]
    step_output: dict[str, Any] | None
    exec_outcome: str
    error_summary: str | None
    error_traceback_str: str | None
    suppress_completion_notification: bool
    runtime: str | None


@dataclass(frozen=True)
class RunnerShutdownDeps:
    update_artifact_index: Callable[[str], Any]
    was_killed: Callable[[], bool]
    all_steps_hidden: Callable[[str], bool]
    write_error_report: Callable[..., str | None]
    send_completion_notification: Callable[..., Any]
    auto_dismiss_completed_agent: Callable[[str, str], Any]


def auto_dismiss_completed_agent(cl_name: str, artifacts_timestamp: str) -> None:
    """Persist auto-dismiss identities for a completed background run."""
    try:
        from sase.ace.dismissed_agents import (
            load_dismissed_agents,
            save_dismissed_agents,
        )

        dismissed = load_dismissed_agents()
        # Dismiss both RUNNING and WORKFLOW identities -- dedup may pick
        # either depending on whether workflow_state.json exists.
        identities = {
            (AgentType.RUNNING, cl_name, artifacts_timestamp),
            (AgentType.WORKFLOW, cl_name, artifacts_timestamp),
        }
        dismissed.update(identities)
        if save_dismissed_agents(dismissed):
            sync_dismissed_agent_artifact_index(dismissed, added=identities)
    except Exception:
        pass  # Best effort


def finalize_runner_shutdown(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
    deps: RunnerShutdownDeps,
) -> None:
    """Run final cleanup, completion marker, error report, and notification."""
    if state.running_marker_path and os.path.exists(state.running_marker_path):
        try:
            os.unlink(state.running_marker_path)
            deps.update_artifact_index(context.artifacts_dir)
        except OSError:
            pass

    if not context.is_home_mode:
        try:
            from sase.running_field import release_workspace

            release_workspace(
                context.project_file,
                state.workspace_num,
                context.workflow_name,
                context.cl_name,
            )
            print("Workspace released")
        except Exception as e:
            print(f"Error releasing workspace: {e}", file=sys.stderr)

    try:
        with open(context.output_path, "a") as f:
            f.write("\n=== AGENT_RUN_COMPLETE ===\n")
            f.write(f"Status: {'SUCCESS' if state.success else 'FAILED'}\n")
            f.write(f"Duration: {state.duration}\n")
    except Exception as e:
        print(f"Error writing completion marker: {e}", file=sys.stderr)

    if os.environ.get("SASE_AGENT_AUTO_DISMISS"):
        deps.auto_dismiss_completed_agent(context.cl_name, context.artifacts_timestamp)

    error_report_path: str | None = None
    if not state.success and state.error_summary:
        error_report_path = deps.write_error_report(
            state.current_artifacts_dir,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            workflow_name=context.workflow_name,
            cl_name=context.cl_name,
            duration=state.duration,
            error_summary=state.error_summary,
            error_traceback=state.error_traceback_str,
            submitted_xprompt=context.submitted_xprompt,
            workspace_dir=state.workspace_dir,
            output_path=context.output_path,
            agent_name=state.agent_name,
        )

    if (
        not state.suppress_completion_notification
        and not deps.was_killed()
        and not deps.all_steps_hidden(state.current_artifacts_dir)
    ):
        deps.send_completion_notification(
            cl_name=context.cl_name,
            artifacts_timestamp=context.artifacts_timestamp,
            workflow_name=context.workflow_name,
            success=state.success,
            agent_hidden=state.agent_hidden,
            agent_name=state.agent_name,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            error_summary=state.error_summary,
            error_report_path=error_report_path,
            saved_path=state.saved_path,
            diff_path=state.diff_path,
            current_artifacts_dir=state.current_artifacts_dir,
            markdown_pdf_paths=state.markdown_pdf_paths,
            markdown_source_count=state.markdown_source_count,
            image_paths=state.image_paths,
            video_paths=state.video_paths,
            output_path=context.output_path,
            step_output=state.step_output,
            prompt=context.prompt,
            outcome=state.exec_outcome,
            runtime=state.runtime,
        )
