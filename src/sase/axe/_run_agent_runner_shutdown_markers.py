"""Completion-marker writing for the run-agent shutdown lifecycle."""

import os
import sys
from collections.abc import Callable
from typing import Any

from sase.axe._run_agent_runner_shutdown_types import (
    RunnerShutdownContext,
    RunnerShutdownState,
)


def _write_hijacked_done_marker(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
) -> None:
    """Write ``outcome: hijacked`` plus pending recovery when none exists."""
    from sase.agent._user_kill_intent import pending_hijack_recovery
    from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
    from sase.axe.run_agent_phases import build_done_marker

    artifacts_dir = state.current_artifacts_dir
    marker = build_done_marker(
        context.cl_name,
        context.project_file,
        context.artifacts_timestamp,
        context.artifacts_timestamp,
        state.workspace_num,
        state.workspace_dir,
        context.output_path,
        "hijacked",
        agent_name=state.agent_name,
        agent_model=state.agent_model,
        agent_llm_provider=state.agent_llm_provider,
        agent_hidden=state.agent_hidden,
        recovery=pending_hijack_recovery(artifacts_dir),
    )
    write_done_marker_and_update_index(str(artifacts_dir), marker)


def ensure_failed_done_marker(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
    write_error_done_marker: Callable[..., Any],
) -> None:
    """Write a failed ``done.json`` when a hold (or error report) has none.

    A pinned workspace claim with no done marker is invisible to ACE and
    the stale-claim sweep, so a hold must never land without one. Best
    effort: log loudly if the marker still cannot be written.
    """
    artifacts_dir = state.current_artifacts_dir
    done_path = os.path.join(artifacts_dir, "done.json")
    if os.path.isfile(done_path):
        return
    if state.exec_outcome == "hijacked":
        try:
            _write_hijacked_done_marker(context=context, state=state)
        except Exception as exc:
            print(
                f"Error writing hijacked done.json for workspace "
                f"#{state.workspace_num}: {exc}",
                file=sys.stderr,
            )
        if not os.path.isfile(done_path):
            print(
                f"Error: workspace #{state.workspace_num} still has no "
                f"done.json at {done_path}",
                file=sys.stderr,
            )
        return
    error = state.error_summary or "workspace held without a done.json marker"
    traceback_str = state.error_traceback_str or ""
    try:
        from sase.axe.runner_failure_facts import capture_failure_facts
        from sase.axe.runner_lifecycle_phase import current_lifecycle_phase

        failure_facts = capture_failure_facts(
            None,
            phase=current_lifecycle_phase(),
            error_text=error,
            traceback_text=traceback_str or None,
        )
        write_error_done_marker(
            current_artifacts_dir=artifacts_dir,
            cl_name=context.cl_name,
            project_file=context.project_file,
            timestamp=context.artifacts_timestamp,
            artifacts_timestamp=context.artifacts_timestamp,
            workspace_num=state.workspace_num,
            workspace_dir=state.workspace_dir,
            output_path=context.output_path,
            agent_name=state.agent_name,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            agent_vcs_provider=None,
            agent_hidden=state.agent_hidden,
            error=error,
            traceback_str=traceback_str,
            failure_facts=failure_facts,
        )
    except Exception as exc:
        print(
            f"Error writing failed done.json for workspace "
            f"#{state.workspace_num}: {exc}",
            file=sys.stderr,
        )
    if not os.path.isfile(done_path):
        print(
            f"Error: workspace #{state.workspace_num} still has no "
            f"done.json at {done_path}",
            file=sys.stderr,
        )
