"""Mutable run state threaded through the ``run_agent_runner`` phases."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sase.axe.run_agent_runner_errors import RunnerErrorContext
from sase.axe.run_agent_runner_lifecycle import (
    RunnerShutdownContext,
    RunnerShutdownState,
)
from sase.bead.claims import BeadClaimMarker


@dataclass
class RunnerRunState:
    """Every runner value that outlives the phase which produced it.

    Bootstrap, dependency wait, launch, and shutdown all refine the same run
    identity, so they share one mutable record instead of threading a dozen
    values through each signature. Shutdown must be able to report whatever was
    known when a phase raised, which is why every outcome field carries a
    pre-failure default.
    """

    # Launch identity parsed from argv.
    cl_name: str
    project_file: str
    prompt_file: str
    output_path: str
    workflow_name: str
    timestamp: str
    update_target: str
    is_home_mode: bool

    # Workspace binding; rebound when a deferred workspace is claimed.
    workspace_dir: str
    workspace_num: int

    # Artifact identity. ``artifacts_dir`` is the launch root, while
    # ``current_artifacts_dir`` tracks the phase directory a plan/retry handoff
    # may have moved into.
    project_name: str
    artifacts_timestamp: str
    artifacts_dir: str
    current_artifacts_dir: str = ""
    # Read by the SIGTERM handler, which needs a destination even before the
    # artifacts directory has been created.
    signal_fallback_artifacts_dir: str | None = None

    # Prompt text. ``submitted_xprompt`` is the launch-boundary snapshot, while
    # ``prompt`` keeps being rewritten by xprompt and agent-ref resolution.
    prompt: str = ""
    submitted_xprompt: str = ""

    # Agent identity, populated by directive extraction.
    agent_name: str | None = None
    agent_model: str | None = None
    agent_llm_provider: str | None = None
    agent_vcs_provider: str | None = None
    agent_hidden: bool = False

    # Outcome and completion reporting.
    start_time: float = field(default_factory=time.time)
    success: bool = False
    duration: str = "0s"
    runtime: str | None = None
    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = field(default_factory=list)
    markdown_source_count: int = 0
    image_paths: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)
    step_output: dict[str, Any] | None = None
    exec_outcome: str = ""
    error_summary: str | None = None
    error_traceback_str: str | None = None
    run_started_at: str | None = None
    suppress_completion_notification: bool = False
    active_agent_started: bool = False
    running_marker_path: str | None = None
    # Set while a waiting agent holds a bead claim it has not yet promoted.
    held_bead_claim: BeadClaimMarker | None = None

    def __post_init__(self) -> None:
        if not self.current_artifacts_dir:
            self.current_artifacts_dir = self.artifacts_dir
        if self.signal_fallback_artifacts_dir is None:
            self.signal_fallback_artifacts_dir = self.artifacts_dir

    def rebind_artifacts_dir(self, artifacts_dir: str) -> None:
        """Point every artifacts-directory view at a newly resolved root."""
        self.artifacts_dir = artifacts_dir
        self.current_artifacts_dir = artifacts_dir
        self.signal_fallback_artifacts_dir = artifacts_dir

    def error_context(self) -> RunnerErrorContext:
        """Snapshot the identity an error marker needs right now."""
        return RunnerErrorContext(
            current_artifacts_dir=self.current_artifacts_dir,
            cl_name=self.cl_name,
            project_file=self.project_file,
            timestamp=self.timestamp,
            artifacts_timestamp=self.artifacts_timestamp,
            workspace_num=self.workspace_num,
            workspace_dir=self.workspace_dir,
            output_path=self.output_path,
            agent_name=self.agent_name,
            agent_model=self.agent_model,
            agent_llm_provider=self.agent_llm_provider,
            agent_vcs_provider=self.agent_vcs_provider,
            agent_hidden=self.agent_hidden,
        )

    def shutdown_context(self) -> RunnerShutdownContext:
        """Snapshot the launch identity shutdown reports against."""
        return RunnerShutdownContext(
            project_file=self.project_file,
            workflow_name=self.workflow_name,
            cl_name=self.cl_name,
            artifacts_timestamp=self.artifacts_timestamp,
            artifacts_dir=self.artifacts_dir,
            output_path=self.output_path,
            submitted_xprompt=self.submitted_xprompt,
            prompt=self.prompt,
            is_home_mode=self.is_home_mode,
        )

    def shutdown_state(self) -> RunnerShutdownState:
        """Snapshot the run outcome shutdown reports."""
        claim = self.held_bead_claim
        return RunnerShutdownState(
            success=self.success,
            duration=self.duration,
            workspace_num=self.workspace_num,
            workspace_dir=self.workspace_dir,
            current_artifacts_dir=self.current_artifacts_dir,
            running_marker_path=self.running_marker_path,
            agent_name=self.agent_name,
            agent_model=self.agent_model,
            agent_llm_provider=self.agent_llm_provider,
            agent_hidden=self.agent_hidden,
            saved_path=self.saved_path,
            diff_path=self.diff_path,
            markdown_pdf_paths=self.markdown_pdf_paths,
            markdown_source_count=self.markdown_source_count,
            image_paths=self.image_paths,
            video_paths=self.video_paths,
            step_output=self.step_output,
            exec_outcome=self.exec_outcome,
            error_summary=self.error_summary,
            error_traceback_str=self.error_traceback_str,
            suppress_completion_notification=self.suppress_completion_notification,
            runtime=self.runtime,
            held_bead_claim_id=claim.bead_id if claim is not None else None,
            held_bead_claim_agent=claim.agent_name if claim is not None else None,
            held_bead_claim_project=claim.project_name if claim is not None else None,
        )
