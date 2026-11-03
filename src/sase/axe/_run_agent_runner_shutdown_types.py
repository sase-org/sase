"""Shared data types for the run-agent shutdown lifecycle."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunnerShutdownContext:
    project_file: str
    workflow_name: str
    cl_name: str
    artifacts_timestamp: str
    artifacts_dir: str
    output_path: str
    submitted_prompt: str
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
    force_silent_notification: bool = False


@dataclass(frozen=True)
class RunnerShutdownDeps:
    update_artifact_index: Callable[[str], Any]
    was_killed: Callable[[], bool]
    all_steps_hidden: Callable[[str], bool]
    write_error_report: Callable[..., str | None]
    write_error_done_marker: Callable[..., Any]
    send_completion_notification: Callable[..., Any]
    auto_dismiss_completed_agent: Callable[[str, str], Any]
