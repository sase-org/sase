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
    WORKFLOW = "workflow"  # Multi-step YAML workflows


@dataclass
class Agent:
    """Represents a single running agent."""

    agent_type: AgentType
    cl_name: str  # ChangeSpec name
    project_file: str  # Path to .gp file
    status: str  # "RUNNING", etc.
    start_time: datetime | None  # Parsed from timestamp suffix
    run_start_time: datetime | None = (
        None  # When agent actually started running (after waiting)
    )
    stop_time: datetime | None = None  # When agent completed (DONE/FAILED)

    # Type-specific fields
    workspace_num: int | None = None  # For RUNNING type
    workflow: str | None = None  # For RUNNING type (e.g., "crs")
    hook_command: str | None = None  # For hook-based agents
    commit_entry_id: str | None = None  # For hook-based agents
    mentor_profile: str | None = None  # For mentor agents
    mentor_name: str | None = None  # For mentor agents
    reviewer: str | None = None  # For CRS agents (e.g., "critique")

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

    # Retry/fallback state (populated from retry_state.json)
    retry_count: int = 0
    max_retries: int = 0
    retry_next_at_epoch: float | None = None
    retry_wait_seconds: int = 0
    using_fallback: bool = False
    fallback_model: str | None = None
    retry_status: str | None = (
        None  # "retrying" | "running_retry" | "running_fallback" | None
    )

    # Whether this agent was loaded from a ChangeSpec field (HOOKS/MENTORS/COMMENTS)
    _from_changespec: bool = False

    # Whether this agent was launched with %approve (fully autonomous)
    approve: bool = False

    # Role suffix annotation (e.g., ".plan", ".code", ".q") for follow-up agents
    role_suffix: str | None = None

    # When plans were submitted for review (one per proposal; plan agents only)
    plan_times: list[datetime] = field(default_factory=list)
    # When the coder agent was launched after plan approval (plan agents only)
    code_time: datetime | None = None
    # When feedback was submitted on the plan (one per feedback round)
    feedback_times: list[datetime] = field(default_factory=list)
    # When the agent submitted questions for user review (one per round)
    questions_times: list[datetime] = field(default_factory=list)

    @property
    def effective_workspace_num(self) -> int | None:
        """Workspace number considering meta_workspace from step_output.

        Workflow step agents may store their workspace number in
        ``step_output["meta_workspace"]`` rather than in :attr:`workspace_num`.
        This property mirrors the display logic in ``_build_header_text``.
        """
        meta_ws = None
        if self.step_output and isinstance(self.step_output, dict):
            raw = self.step_output.get("meta_workspace")
            if raw is not None:
                try:
                    meta_ws = int(raw)
                except (ValueError, TypeError):
                    pass
        if meta_ws is not None:
            return meta_ws
        return self.workspace_num

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
        return "agent"

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
    def timestamps_display(self) -> str:
        """Multi-timestamp display for the metadata panel.

        Each timestamp on its own line, with subsequent lines indented
        to align with the first (matching the width of ``Timestamps: ``).

        - WAIT shown only when agent waited before starting (run_start_time exists)
        - BEGIN always shown
        - END shown for DONE/FAILED agents
        """
        parts: list[str] = []
        fmt = "%Y-%m-%d %H:%M:%S"
        # Pad tag to 5 chars so timestamps align (longest tag is 5: BEGIN)
        tag_width = 5

        def _fmt(tag: str, ts: str) -> str:
            return f"{tag.ljust(tag_width)} | {ts}"

        # If the agent waited, show WAIT (original start_time) then BEGIN (run_start_time)
        if self.run_start_time is not None and self.start_time is not None:
            parts.append(_fmt("WAIT", self.start_time.strftime(fmt)))
            parts.append(_fmt("BEGIN", self.run_start_time.strftime(fmt)))
        elif self.start_time is not None:
            # WAITING agents haven't started yet — start_time is their spawn time
            tag = "WAIT" if self.status == "WAITING" else "BEGIN"
            parts.append(_fmt(tag, self.start_time.strftime(fmt)))
        else:
            parts.append(_fmt("BEGIN", "Unknown"))

        # Collect remaining timestamps and sort chronologically
        middle: list[tuple[datetime, str]] = []
        for pt in self.plan_times:
            middle.append((pt, "PLAN"))
        for ft in self.feedback_times:
            middle.append((ft, "FBACK"))
        for qt in self.questions_times:
            middle.append((qt, "QUEST"))
        if self.code_time is not None:
            middle.append((self.code_time, "CODE"))
        middle.sort(key=lambda t: t[0])
        for ts, tag in middle:
            parts.append(_fmt(tag, ts.strftime(fmt)))

        if self.stop_time is not None:
            parts.append(_fmt("END", self.stop_time.strftime(fmt)))

        # Indent subsequent lines by width of "Timestamps: " (12 chars)
        indent = " " * 12
        return ("\n" + indent).join(parts)

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
        end = self.stop_time or datetime.now()
        delta = end - self.start_time
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
        RUNNING agents, plus WORKFLOW entries that appear as agents
        and workflow child steps of type ``agent``.
        """
        if self.agent_type == AgentType.RUNNING:
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
            elif workflow.startswith("axe(fix-hook)"):
                workflow_name = "fix-hook"
            elif workflow.startswith("axe(crs)"):
                workflow_name = "crs"
            elif workflow.startswith("axe(mentor)"):
                # "axe(mentor)-complete-TIMESTAMP" -> "mentor-complete"
                parts = workflow.split("-")
                workflow_name = f"mentor-{parts[1]}" if len(parts) >= 2 else "mentor"
            elif workflow.startswith("mentor(") and workflow.endswith(")"):
                # "mentor(code_quality)" -> artifacts dir "mentor-code_quality"
                profile = workflow[7:-1]
                workflow_name = f"mentor-{profile}"
            elif workflow == "mentor" and self.mentor_name:
                # ChangeSpec-sourced mentor: workflow="mentor", mentor_name="code_quality"
                # -> artifacts dir "mentor-code_quality"
                workflow_name = f"mentor-{self.mentor_name}"
            elif workflow == "fix_hook":
                # VCS workspace claim uses "fix_hook" (from xprompt
                # workflow_label) but artifacts dir is "fix-hook"
                workflow_name = "fix-hook"
            else:
                workflow_name = workflow
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
        For ChangeSpec-sourced agents: raw_suffix uses YYmmdd_HHMMSS format (13 chars with underscore)
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
            elif isinstance(value, list) and value and isinstance(value[0], datetime):
                value = [v.isoformat() for v in value]
            result[f.name] = value
        return result

    @staticmethod
    def from_bundle_dict(data: dict[str, Any]) -> "Agent":
        """Reconstruct an Agent from a bundle dict.

        Uses .get() with defaults for forward-compatibility with new fields.
        """
        # Map removed AgentType values to RUNNING for backward compatibility
        _LEGACY_AGENT_TYPES = {"fix-hook", "summarize", "mentor", "crs"}
        raw_type = data["agent_type"]
        if raw_type in _LEGACY_AGENT_TYPES:
            agent_type = AgentType.RUNNING
        else:
            agent_type = AgentType(raw_type)
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

        # Backward compat: old bundles stored singular datetime fields
        for old, new in (
            ("plan_time", "plan_times"),
            ("feedback_time", "feedback_times"),
            ("questions_time", "questions_times"),
        ):
            if old in data and new not in data:
                raw = data.pop(old)
                if isinstance(raw, str):
                    data[new] = [raw]

        # Populate all optional fields from the bundle
        _DATETIME_FIELDS = {
            "run_start_time",
            "stop_time",
            "code_time",
        }
        _DATETIME_LIST_FIELDS = {"plan_times", "feedback_times", "questions_times"}
        for f in dataclasses.fields(Agent):
            if f.name in kwargs:
                continue
            if f.name not in data:
                continue
            value = data[f.name]
            # Skip None values for fields with non-None defaults (list fields)
            if value is None and f.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
                continue
            # Deserialize ISO datetime strings for datetime fields
            if f.name in _DATETIME_FIELDS and isinstance(value, str):
                value = datetime.fromisoformat(value)
            elif f.name in _DATETIME_LIST_FIELDS and isinstance(value, list):
                value = [
                    datetime.fromisoformat(v) if isinstance(v, str) else v
                    for v in value
                ]
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

    def get_live_reply_content(self) -> str | None:
        """Get the live reply content for running agents.

        Returns:
            Live reply content string, or None if not available.
        """
        artifacts_dir = self.get_artifacts_dir()
        if artifacts_dir is None:
            return None
        path = os.path.join(artifacts_dir, "live_reply.md")
        try:
            with open(path, encoding="utf-8") as f:
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
