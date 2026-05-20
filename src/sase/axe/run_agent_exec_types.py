"""Shared data structures for agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.main.qa_markdown import QARound


@dataclass
class AgentExecContext:
    """Immutable configuration the execution loop needs from the runner."""

    cl_name: str
    project_file: str
    workspace_dir: str
    output_path: str
    workspace_num: int
    timestamp: str
    update_target: str
    project_name: str
    is_home_mode: bool
    artifacts_dir: str
    artifacts_timestamp: str
    vcs_tag: str | None
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_vcs_provider: str | None
    agent_hidden: bool
    agent_meta: dict[str, Any]
    local_xprompts: dict[str, Any]
    wait_chats: list[str] = field(default_factory=list)


@dataclass
class AgentExecResult:
    """Result from the execution loop."""

    success: bool
    outcome: str = "completed"
    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = field(default_factory=list)
    markdown_source_count: int = 0
    image_paths: list[str] = field(default_factory=list)
    current_artifacts_dir: str = ""
    step_output: dict[str, Any] | None = None


@dataclass
class LoopState:
    """Mutable state for the execution loop."""

    current_prompt: str
    current_role_suffix: str
    current_artifacts_dir: str
    loop_outcome: str
    sdd_spec_path: str | None
    # The bare initial prompt with no accumulated Q&A or feedback appended.
    original_prompt: str
    qa_rounds: list[QARound] = field(default_factory=list)
    feedback_bullets: list[str] = field(default_factory=list)
    feedback_round: int = 0
    agent_step: int = 1
    saved_chat_paths: list[tuple[str, str]] = field(default_factory=list)
    # Snapshot of SASE_AGENT_TIMESTAMP at loop entry, restored after finalization.
    original_agent_timestamp: str | None = None


_AgentExecResult = AgentExecResult
