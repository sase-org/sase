"""Shutdown and completion helpers for ``run_agent_runner``."""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.bead.claims import (
    BeadClaimMarker,
    clear_bead_claim_marker,
    read_bead_claim_marker,
)
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import (
    load_dismissed_agents,
    persist_dismissed_agents as save_dismissed_agents,
)
from sase.axe.run_agent_monitor_handoff import monitor_handoff_claim_transferred

_NON_HOLD_FAILURE_OUTCOMES = {
    "killed",
    "failed_retried",
    "plan_rejected",
    "plan_committed",
    "epic_approved",
    "epic_launch_failed",
}


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
    held_bead_claim_id: str | None = None
    held_bead_claim_agent: str | None = None
    held_bead_claim_project: str | None = None


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


def _should_hold_workspace(
    state: RunnerShutdownState,
    *,
    was_killed: bool,
    auto_dismiss: bool,
    steps_hidden: bool,
) -> bool:
    """Return whether this failed run has a visible dismissal path."""
    return (
        not state.success
        and state.exec_outcome not in _NON_HOLD_FAILURE_OUTCOMES
        and not was_killed
        and not auto_dismiss
        and not steps_hidden
        and not state.suppress_completion_notification
    )


def _held_bead_claim_from_state(
    state: RunnerShutdownState,
) -> BeadClaimMarker | None:
    if (
        state.held_bead_claim_id
        and state.held_bead_claim_agent
        and state.held_bead_claim_project
    ):
        return BeadClaimMarker(
            bead_id=state.held_bead_claim_id,
            agent_name=state.held_bead_claim_agent,
            project_name=state.held_bead_claim_project,
        )
    return None


def _agent_meta_has_promoted_bead_claim(artifacts_dir: str) -> bool:
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return isinstance(payload, dict) and payload.get("bead_claim_promoted") is True


def _held_bead_claim_for_shutdown(
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
) -> BeadClaimMarker | None:
    return _held_bead_claim_from_state(state) or read_bead_claim_marker(
        context.artifacts_dir
    )


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

    auto_dismiss = bool(os.environ.get("SASE_AGENT_AUTO_DISMISS"))
    workspace_held = False
    killed = deps.was_killed()
    steps_hidden = deps.all_steps_hidden(state.current_artifacts_dir)
    monitor_handoff_transferred = (
        state.exec_outcome == "monitored"
        and monitor_handoff_claim_transferred(
            context.project_file,
            state.workspace_num,
            cl_name=context.cl_name,
        )
    )
    if not context.is_home_mode and not monitor_handoff_transferred:
        try:
            if _should_hold_workspace(
                state,
                was_killed=killed,
                auto_dismiss=auto_dismiss,
                steps_hidden=steps_hidden,
            ):
                from sase.running_field import hold_workspace_claim

                result = hold_workspace_claim(
                    context.project_file,
                    state.workspace_num,
                    context.workflow_name,
                    context.cl_name,
                    context.artifacts_timestamp,
                )
                workspace_held = result.success
                if workspace_held:
                    print(
                        f"Workspace #{state.workspace_num} held (visible failed run) — "
                        "dismiss the agent in ace to release it"
                    )
                else:
                    print(
                        f"Error holding workspace #{state.workspace_num}: "
                        f"{result.error or 'unknown error'}",
                        file=sys.stderr,
                    )
            else:
                from sase.running_field import release_workspace

                release_workspace(
                    context.project_file,
                    state.workspace_num,
                    context.workflow_name,
                    context.cl_name,
                )
                print("Workspace released")
        except Exception as e:
            print(f"Error updating workspace claim: {e}", file=sys.stderr)

    held_bead_claim = _held_bead_claim_for_shutdown(context, state)
    if held_bead_claim is not None:
        try:
            from sase.agent.pending_handoff import has_pending_handoff

            if not has_pending_handoff(
                context.artifacts_dir
            ) and not _agent_meta_has_promoted_bead_claim(context.artifacts_dir):
                from sase.bead.claims import (
                    BeadClaimReleaseOutcome,
                    release_bead_claim_for_agent,
                )

                outcome = release_bead_claim_for_agent(
                    project_name=held_bead_claim.project_name,
                    bead_id=held_bead_claim.bead_id,
                    agent_name=held_bead_claim.agent_name,
                )
                if outcome is not BeadClaimReleaseOutcome.ERROR:
                    clear_bead_claim_marker(context.artifacts_dir)
        except Exception as e:
            print(
                f"Warning: Failed to release waiting bead claim: {e}", file=sys.stderr
            )

    try:
        with open(context.output_path, "a") as f:
            f.write("\n=== AGENT_RUN_COMPLETE ===\n")
            f.write(f"Status: {'SUCCESS' if state.success else 'FAILED'}\n")
            f.write(f"Duration: {state.duration}\n")
    except Exception as e:
        print(f"Error writing completion marker: {e}", file=sys.stderr)

    if auto_dismiss:
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
            held_workspace_num=state.workspace_num if workspace_held else None,
            output_path=context.output_path,
            agent_name=state.agent_name,
        )

    if not state.suppress_completion_notification and not killed and not steps_hidden:
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
            held_workspace_num=state.workspace_num if workspace_held else None,
            held_workspace_dir=state.workspace_dir if workspace_held else None,
        )
