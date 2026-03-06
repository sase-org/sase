"""Agent data model for the Agents tab."""

import dataclasses
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class AgentType(Enum):
    """Types of agents that can be tracked."""

    RUNNING = "run"  # Manual sase run commands (RUNNING field)
    FIX_HOOK = "fix-hook"  # Fix-hook agents (HOOKS suffix_type=running_agent)
    SUMMARIZE = "summarize"  # Summarize-hook agents (HOOKS)
    MENTOR = "mentor"  # Mentor agents (MENTORS)
    CRS = "crs"  # Comment Resolution System (COMMENTS)
    WORKFLOW = "workflow"  # Multi-step YAML workflows


@dataclass
class Agent:
    """Represents a single running agent."""

    agent_type: AgentType
    cl_name: str  # ChangeSpec name
    project_file: str  # Path to .gp file
    status: str  # "RUNNING", etc.
    start_time: datetime | None  # Parsed from timestamp suffix

    # Type-specific fields
    workspace_num: int | None = None  # For RUNNING type
    workflow: str | None = None  # For RUNNING type (e.g., "crs")
    hook_command: str | None = None  # For FIX_HOOK/SUMMARIZE types
    commit_entry_id: str | None = None  # For hook-based agents
    mentor_profile: str | None = None  # For MENTOR type
    mentor_name: str | None = None  # For MENTOR type
    reviewer: str | None = None  # For CRS type (e.g., "critique")

    # PID for process management
    pid: int | None = None

    # For agent suffix parsing
    raw_suffix: str | None = None

    # Response file path for completed agents
    response_path: str | None = None

    # Diff file path for completed agents
    diff_path: str | None = None

    # Additional file paths (plans, etc.) for multi-file panel display
    extra_files: list[str] = field(default_factory=list)

    # Bug URL for agents with associated bug IDs
    bug: str | None = None

    # CL number for agents with associated CL
    cl_num: str | None = None

    # Parent workflow name for agent steps within workflows
    parent_workflow: str | None = None

    # Parent timestamp for agent steps (links to parent workflow entry)
    parent_timestamp: str | None = None

    # Workflow step name (clean, without tree decoration)
    step_name: str | None = None

    # Type of workflow step: "agent", "bash", or "python"
    step_type: str | None = None

    # Source code/command for bash/python steps
    step_source: str | None = None

    # Step output data
    step_output: dict[str, Any] | None = None

    # Step index for ordering (0-based)
    step_index: int | None = None

    # Total steps in the parent workflow (for step numbering display)
    total_steps: int | None = None

    # Parent step index for embedded workflow steps (0-based)
    parent_step_index: int | None = None

    # Total steps in the grandparent workflow (for embedded step display)
    parent_total_steps: int | None = None

    # Whether this is a hidden workflow step (hidden by default in Agents tab)
    is_hidden_step: bool = False

    # Workflow that looks like an agent (all non-prompt steps hidden)
    appears_as_agent: bool = False

    # Anonymous (temporary) workflow created for ad-hoc runs
    is_anonymous: bool = False

    # Error message for failed agents (from HookStatusLine.suffix)
    error_message: str | None = None

    # Full traceback string for failed agents
    error_traceback: str | None = None

    # Runner stdout/stderr output file path (for debugging failed agents)
    output_path: str | None = None

    # Model name from %model directive (only when explicitly set)
    model: str | None = None

    # LLM provider name (e.g., "claude", "gemini")
    llm_provider: str | None = None

    # VCS provider display name (e.g., "GitHub", "Mercurial")
    vcs_provider: str | None = None

    # Agent name assigned via %name directive or manual TUI naming
    agent_name: str | None = None

    # Names this agent is waiting for (from %wait directives)
    waiting_for: list[str] = field(default_factory=list)

    # Explicit artifacts directory path (for workflow steps loaded from marker files)
    artifacts_dir: str | None = None

    # Embedded workflow name for steps within embedded workflows (e.g., "git", "propose")
    embedded_workflow_name: str | None = None

    # Whether this is a pre-prompt step from an embedded workflow
    is_pre_prompt_step: bool = False

    # Whether this agent should be hidden by default (shown with '.' toggle)
    hidden: bool = False

    # Whether this agent was launched with %approve (fully autonomous)
    approve: bool = False

    # Current retry attempt (1 = first try, 2 = first retry, etc.)
    retry_attempt: int = 0

    def get_display_type(self, *, is_expanded: bool = False) -> str:
        """Compute display type with optional fold-state context.

        When collapsed: always [agent].
        When expanded: [workflow] for anonymous, [<workflow_name>] for named.
        """
        if self.appears_as_agent:
            if not is_expanded:
                return "agent"
            if self.is_anonymous:
                return "workflow"
            return self.workflow if self.workflow else "agent"
        if self.is_workflow_child and self.step_type:
            return self.step_type
        if self.agent_type == AgentType.RUNNING:
            return "agent"
        return self.agent_type.value

    @property
    def display_type(self) -> str:
        """Human-readable agent type for display (default: collapsed context)."""
        return self.get_display_type(is_expanded=False)

    @property
    def display_name(self) -> str:
        """Name to show in list display.

        Top-level workflow entries show the workflow name (e.g. "refresh_cl_desc")
        instead of the CL name, since that's what the user cares about.
        """
        if (
            self.agent_type == AgentType.WORKFLOW
            and not self.appears_as_agent
            and not self.is_workflow_child
            and self.workflow
        ):
            return self.workflow
        return self.cl_name

    @property
    def display_label(self) -> str:
        """Combined label for list display: Type + name."""
        return f"[{self.display_type}] {self.display_name}"

    @property
    def start_time_display(self) -> str:
        """Formatted start time for display."""
        if self.start_time is None:
            return "Unknown"
        return self.start_time.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def start_time_short(self) -> str:
        """Short formatted start time (HH:MM) for list display."""
        if self.start_time is None:
            return "?"
        return self.start_time.strftime("%H:%M")

    @property
    def duration_display(self) -> str:
        """Display how long the agent has been running."""
        if self.start_time is None:
            return "?"
        delta = datetime.now() - self.start_time
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h{minutes}m"
        elif minutes > 0:
            return f"{minutes}m{seconds}s"
        else:
            return f"{seconds}s"

    @property
    def all_files(self) -> list[str]:
        """All displayable file paths (diff + extras) for multi-file panel."""
        files: list[str] = []
        if self.diff_path:
            files.append(self.diff_path)
        files.extend(self.extra_files)
        return files

    @property
    def identity(self) -> tuple["AgentType", str, str | None]:
        """Unique identifier for this agent instance."""
        return (self.agent_type, self.cl_name, self.raw_suffix)

    @property
    def is_workflow_child(self) -> bool:
        """Check if this agent is a child step of a workflow."""
        return self.parent_workflow is not None or self.parent_timestamp is not None

    @property
    def is_agent_entry(self) -> bool:
        """Check if this entry represents an agent process (with thinking support).

        Agent entries run an LLM agent and may have thinking blocks:
        RUNNING, FIX_HOOK, MENTOR, CRS agents, plus WORKFLOW entries
        that appear as agents and workflow child steps of type ``agent``.
        """
        if self.agent_type in (
            AgentType.RUNNING,
            AgentType.FIX_HOOK,
            AgentType.MENTOR,
            AgentType.CRS,
        ):
            return True
        if self.agent_type == AgentType.WORKFLOW:
            if self.appears_as_agent:
                return True
            if self.is_workflow_child and self.step_type == "agent":
                return True
        return False

    @property
    def is_project_agent(self) -> bool:
        """Check if this agent runs against a project (not a specific ChangeSpec)."""
        if not self.project_file:
            return False
        project_name = Path(self.project_file).parent.name
        return self.cl_name == project_name

    def get_artifacts_dir(self) -> str | None:
        """Get the artifacts directory path for this agent.

        Returns:
            Path to the artifacts directory, or None if it cannot be determined.
        """
        # If we have an explicit artifacts_dir (from marker files), use it directly
        if self.artifacts_dir and os.path.isdir(self.artifacts_dir):
            return self.artifacts_dir

        # Extract project name from project_file
        # Format: ~/.sase/projects/<project>/<project>.gp
        project_path = Path(self.project_file)
        project_name = project_path.parent.name

        # Determine workflow name based on agent type
        if self.agent_type == AgentType.RUNNING:
            workflow = self.workflow or "run"
            # Extract base workflow: "ace(run)-timestamp" -> "ace-run"
            if workflow.startswith("ace(run)"):
                workflow_name = "ace-run"
            else:
                workflow_name = workflow
        elif self.agent_type == AgentType.FIX_HOOK:
            workflow_name = "fix-hook"
        elif self.agent_type == AgentType.SUMMARIZE:
            workflow_name = "summarize-hook"
        elif self.agent_type == AgentType.MENTOR:
            if self.mentor_name:
                workflow_name = f"mentor-{self.mentor_name}"
            else:
                workflow_name = "mentor"
        elif self.agent_type == AgentType.CRS:
            workflow_name = "crs"
        elif self.agent_type == AgentType.WORKFLOW:
            # Workflow artifacts: workflow-{name}, or ace-run for appears_as_agent
            if self.workflow:
                base_workflow = (
                    self.workflow.split("/")[-1]
                    if "/" in self.workflow
                    else self.workflow
                )
                # appears_as_agent workflows may use ace-run/ artifacts dir
                if self.appears_as_agent:
                    ace_run_dir = os.path.expanduser(
                        f"~/.sase/projects/{project_name}/artifacts/ace-run"
                    )
                    if os.path.isdir(ace_run_dir):
                        timestamp = self._extract_artifacts_timestamp()
                        if timestamp:
                            candidate = os.path.join(ace_run_dir, timestamp)
                            if os.path.isdir(candidate):
                                return candidate
                workflow_name = f"workflow-{base_workflow}"
            else:
                return None
        else:
            return None

        # Extract and convert timestamp from raw_suffix
        # raw_suffix format: <agent>-<PID>-YYmmdd_HHMMSS or similar
        # artifacts_dir expects: YYYYmmddHHMMSS
        if self.raw_suffix is None:
            return None

        timestamp = self._extract_artifacts_timestamp()
        if timestamp is None:
            return None

        # Construct path
        artifacts_dir = os.path.expanduser(
            f"~/.sase/projects/{project_name}/artifacts/{workflow_name}/{timestamp}"
        )

        if os.path.isdir(artifacts_dir):
            return artifacts_dir

        return None

    def _extract_artifacts_timestamp(self) -> str | None:
        """Extract and convert timestamp from raw_suffix to artifacts format.

        For RUNNING agents: raw_suffix is already YYYYmmddHHMMSS (14 chars)
        For other agents: raw_suffix uses YYmmdd_HHMMSS format (13 chars with underscore)
        artifacts_dir expects: YYYYmmddHHMMSS format (14 chars, no underscore)

        Returns:
            Converted timestamp string, or None if parsing fails.
        """
        if self.raw_suffix is None:
            return None

        # For RUNNING agents, raw_suffix is the timestamp directly (14 chars)
        if len(self.raw_suffix) == 14 and self.raw_suffix.isdigit():
            return self.raw_suffix

        # Extract timestamp part from suffix
        ts: str | None = None

        if "-" in self.raw_suffix:
            parts = self.raw_suffix.split("-")
            if len(parts) >= 2:
                ts = parts[-1]
        else:
            ts = self.raw_suffix

        # Validate and convert format: YYmmdd_HHMMSS -> YYYYmmddHHMMSS
        if ts and len(ts) == 13 and ts[6] == "_":
            # Add century prefix and remove underscore
            return f"20{ts[:6]}{ts[7:]}"

        return None

    def to_bundle_dict(self) -> dict[str, Any]:
        """Serialize this Agent to a dict for bundle persistence.

        Converts AgentType to string and datetime to ISO format string.
        """
        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, AgentType):
                value = value.value
            elif isinstance(value, datetime):
                value = value.isoformat()
            result[f.name] = value
        return result

    @staticmethod
    def from_bundle_dict(data: dict[str, Any]) -> "Agent":
        """Reconstruct an Agent from a bundle dict.

        Uses .get() with defaults for forward-compatibility with new fields.
        """
        agent_type = AgentType(data["agent_type"])
        start_time = data.get("start_time")
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)

        kwargs: dict[str, Any] = {
            "agent_type": agent_type,
            "cl_name": data["cl_name"],
            "project_file": data["project_file"],
            "status": data["status"],
            "start_time": start_time,
        }

        # Populate all optional fields from the bundle
        for f in dataclasses.fields(Agent):
            if f.name in kwargs:
                continue
            if f.name not in data:
                continue
            value = data[f.name]
            # Skip None values for fields with non-None defaults (list fields)
            if value is None and f.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
                continue
            kwargs[f.name] = value

        return Agent(**kwargs)

    def get_raw_xprompt_content(self) -> str | None:
        """Get the raw xprompt content (before preprocessing/expansion).

        Returns:
            Raw xprompt content string, or None if not available.
        """
        artifacts_dir = self.get_artifacts_dir()
        if artifacts_dir is None:
            return None
        raw_path = os.path.join(artifacts_dir, "raw_xprompt.md")
        try:
            with open(raw_path, encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, OSError):
            return None

    def get_response_content(self) -> str | None:
        """Get the response content for DONE agents.

        Returns:
            Response content string, or None if not available.
        """
        if self.response_path is None:
            return None
        try:
            with open(os.path.expanduser(self.response_path), encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
