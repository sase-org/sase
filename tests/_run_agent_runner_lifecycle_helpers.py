"""Shared helpers for run_agent_runner_lifecycle shutdown tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from sase.axe.run_agent_runner_lifecycle import (
    RunnerShutdownContext,
    RunnerShutdownDeps,
    RunnerShutdownState,
)


def make_state(**overrides: object) -> RunnerShutdownState:
    """Return a failed-run shutdown state with ``overrides`` applied."""
    state = RunnerShutdownState(
        success=False,
        duration="1s",
        workspace_num=17,
        workspace_dir="/tmp/workspace-17",
        current_artifacts_dir="/tmp/artifacts",
        running_marker_path=None,
        agent_name="worker",
        agent_model="model",
        agent_llm_provider="provider",
        agent_hidden=False,
        saved_path=None,
        diff_path=None,
        markdown_pdf_paths=[],
        markdown_source_count=0,
        image_paths=[],
        video_paths=[],
        step_output=None,
        exec_outcome="",
        error_summary="RuntimeError: boom",
        error_traceback_str=None,
        suppress_completion_notification=False,
        runtime="1s",
    )
    return replace(state, **overrides)


def make_context(
    tmp_path: Path,
    *,
    workflow_name: str = "run",
    is_home_mode: bool = False,
) -> RunnerShutdownContext:
    """Return a shutdown context whose artifacts live under ``tmp_path``."""
    return RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name=workflow_name,
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=is_home_mode,
    )


def make_deps(
    *,
    was_killed: MagicMock | None = None,
    all_steps_hidden: MagicMock | None = None,
    write_error_report: MagicMock | None = None,
    send_completion_notification: MagicMock | None = None,
) -> RunnerShutdownDeps:
    """Return shutdown deps; pass mocks for the ones a test tunes or asserts on."""
    return RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=(
            MagicMock(return_value=False) if was_killed is None else was_killed
        ),
        all_steps_hidden=(
            MagicMock(return_value=True)
            if all_steps_hidden is None
            else all_steps_hidden
        ),
        write_error_report=(
            MagicMock() if write_error_report is None else write_error_report
        ),
        send_completion_notification=(
            MagicMock()
            if send_completion_notification is None
            else send_completion_notification
        ),
        auto_dismiss_completed_agent=MagicMock(),
    )
