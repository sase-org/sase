"""Agent data model for the Agents tab."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sase.core.paths import shorten_path
from sase.core.time import local_now
from sase.project_display_names import humanize_cl_name

from .agent_attempt import AttemptRecord, load_attempt_history
from .agent_source import agent_source
from .agent_time import (
    compute_row_runtime,
    format_compact_duration,
    format_wait_until,
    row_runtime_or_wait_ticks,
    should_display_runtime_suffix,
    wait_countdown_ticks,
    wait_display_agent,
    wait_remaining_seconds,
    wait_until_target_and_reference,
)

__all__ = [
    "Agent",
    "AgentChildLinkage",
    "AgentType",
    "AttemptRecord",
    "LinkedRepoMetadata",
    "agent_source",
    "compute_row_runtime",
    "format_compact_duration",
    "format_wait_until",
    "row_runtime_or_wait_ticks",
    "should_display_runtime_suffix",
    "wait_countdown_ticks",
    "wait_display_agent",
    "wait_remaining_seconds",
    "wait_until_target_and_reference",
    "load_attempt_history",
]


class AgentType(Enum):
    """Types of agents that can be tracked."""

    RUNNING = "run"  # Manual sase run commands (RUNNING field)
    WORKFLOW = "workflow"  # Multi-step YAML workflows


class AgentChildLinkage(Enum):
    """How an agent row links to a parent row in the Agents tab."""

    ROOT = "root"
    WORKFLOW_STEP = "workflow_step"
    FAMILY_MEMBER = "family_member"


@dataclass(frozen=True)
class LinkedRepoMetadata:
    """Resolved linked repository metadata recorded for an agent run."""

    name: str
    workspace_dir: str


@dataclass
class Agent:
    """Represents a single running agent."""

    agent_type: AgentType
    cl_name: str  # ChangeSpec name
    project_file: str  # Path to project spec file
    status: str  # "RUNNING", etc.
    start_time: datetime | None  # Parsed from timestamp suffix
    run_start_time: datetime | None = (
        None  # When agent actually started running (after waiting)
    )
    wait_start_time: datetime | None = None  # Launch timestamp for waited agents
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

    # Precomputed badge classification for ``diff_path``. None means the row
    # has not gone through the loader classification pass yet.
    diff_has_real_edits: bool | None = field(default=None, compare=False)

    # Precomputed live-primary-first file-change hint for active agents.
    # Populated by the deferred live-hint refresh (off the event loop) and
    # carried across reloads as stale-while-revalidate state. It supersedes the
    # persisted primary classification while active; terminal rows keep the
    # persisted classification authoritative. None means "no live signal yet".
    live_file_change_hint: bool | None = field(default=None, compare=False)

    # Precomputed badge classification for persisted linked-repo commit diffs.
    # None means no linked diff metadata was available to classify.
    linked_file_change_hint: bool | None = field(default=None, compare=False)

    # Additional file paths (plans, etc.) for multi-file panel display
    extra_files: list[str] = field(default_factory=list)

    # Canonical plan association for detail-header enrichment. The source
    # references are retained so approval changes can switch between the
    # durable local archive and the committed SDD copy without re-reading
    # marker files on the render path.
    plan_path: str | None = None
    archived_plan_path: str | None = None
    sdd_plan_path: str | None = None
    plan_committed: bool | None = None

    # Explicit bead association metadata used by approved epic/phase work.
    # Agent names remain a supported fallback for older bead-work records.
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None

    # Bug URL for agents with associated bug IDs
    bug: str | None = None

    # PR number for agents with associated PR
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

    # Whether this workflow step belongs to an appears-as-agent parent workflow
    parent_appears_as_agent: bool = False

    # Workflow that looks like an agent (all non-prompt steps hidden)
    appears_as_agent: bool = False

    # Anonymous (temporary) workflow created for ad-hoc runs
    is_anonymous: bool = False

    # Error message for failed agents (from HookStatusLine.suffix)
    error_message: str | None = None

    # Full traceback string for failed agents
    error_traceback: str | None = None

    # Transient activity surfaced from workflow_state.json while finalization
    # work is still running (for example Markdown PDF construction).
    activity: str | None = None
    pdf_status: dict[str, Any] | None = None

    # Runner stdout/stderr output file path (for debugging failed agents)
    output_path: str | None = None

    # Model name from %model directive (only when explicitly set)
    model: str | None = None

    # LLM provider name (e.g., "claude", "agy")
    llm_provider: str | None = None

    # Effective reasoning-effort level (e.g. "xhigh"), resolved from the
    # %effort/@effort directive or llm_provider.default_effort. Rendered as a
    # uniform suffix on the Model field across every provider.
    reasoning_effort: str | None = None

    # VCS provider display name (e.g., "GitHub", "Mercurial")
    vcs_provider: str | None = None

    # Resolved directory the agent ran in. This matters for directory-mode
    # agents where workspace_num is 0 and no RUNNING-field claim exists.
    workspace_dir: str | None = None

    # Linked repositories resolved at agent launch. Populated from
    # ``agent_meta.json["linked_repos"]`` during existing metadata enrichment.
    linked_repos: tuple[LinkedRepoMetadata, ...] = field(
        default_factory=tuple,
        compare=False,
    )

    # Agent name assigned via %name directive or manual TUI naming
    agent_name: str | None = None

    # Names this agent is waiting for (from %wait directives)
    waiting_for: list[str] = field(default_factory=list)

    # Duration wait in seconds (from %wait(time=5m) directive)
    wait_duration: float | None = None

    # Absolute time wait target as ISO 8601 string (from %wait(time=1430) directive)
    wait_until: str | None = None

    # Runner-slot wait metadata projected from waiting.json. ``wait_runners``
    # is the existing-runner threshold; config-gated waits render the total
    # cap as threshold + 1, while explicit %wait(runners=N) waits render N.
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    slot_requested_at: str | None = None

    # Snapshot-derived display context. These values are recomputed from the
    # already-loaded Agents refresh payload after full and artifact-delta
    # merges; rendering them never triggers another filesystem scan. Queue
    # position and size include only waiters eligible at the current count.
    runner_slots_in_use: int | None = None
    runner_slot_queue_position: int | None = None
    runner_slot_queue_size: int | None = None

    # True while this row's own pending_question.json marker exists. Root rows
    # with this flag have yielded their runner slot; family status propagation
    # must not be used as a substitute because a child question remains exempt.
    runner_slot_yielded: bool = False

    # Explicit artifacts directory path (for workflow steps loaded from marker files)
    artifacts_dir: str | None = None

    # Embedded workflow name for steps within embedded workflows (e.g., "git", "propose")
    embedded_workflow_name: str | None = None

    # Whether this is a pre-prompt step from an embedded workflow
    is_pre_prompt_step: bool = False

    # Whether this agent should be hidden by default (shown with '.' toggle)
    hidden: bool = False

    # Whether this agent's commits were reverted via the Agents-tab `,r` action
    # (detected from revert_result.json in the agent's artifacts dir at load time).
    reverted: bool = False

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

    # Whether this agent has plan auto-approval enabled (via %auto, %auto:tale,
    # %auto:epic, or the Auto-Approve menu). Stays True in memory for tale/epic
    # — it drives the ⚡ row icon — even though the persisted ``approve`` key is
    # omitted for those (the action below carries the kind).
    approve: bool = False

    # Explicit plan auto-approval action: "tale" or "epic" (None means a normal
    # plan approval). Renders as the ⚡T / ⚡E row-icon suffix.
    auto_approve_plan_action: str | None = None

    # The plan action chosen at approval time, e.g. "tale", "epic", "commit".
    # Persisted in agent_meta.json so the parent's approved-status
    # variant can be reconstructed across `sase ace` restart even after the
    # workflow itself has completed.
    plan_action: str | None = None

    # Role suffix annotation (e.g., ".plan", ".code", ".q") for follow-up agents
    role_suffix: str | None = None

    # Agent-family metadata for plan/question/feedback/coder handoff flows.
    agent_family: str | None = None
    agent_family_role: str | None = None
    plan_chain_root: bool = False
    # Display-only status labels from custom role definitions. These never
    # replace the semantic ``status`` string used for bucketing/actions.
    custom_role_label: str | None = None
    custom_role_done_label: str | None = None

    # User-managed tag (no '@' prefix; at most one per agent).
    # Populated from ``~/.sase/agent_tags.json`` after agents are loaded.
    tag: str | None = None

    # Agent-scoped output variables written by ``sase var set``.
    output_variables: dict[str, str] = field(default_factory=dict)

    # Follow-up agents linked to this parent (populated at load time, not serialized)
    followup_agents: list["Agent"] = field(default_factory=list)

    # Child agents whose intervals contribute to this row's aggregate runtime
    # (populated at load time, not serialized).
    runtime_children: list["Agent"] = field(default_factory=list)

    # WAITING child row whose wait metadata should drive this row's display.
    # Runtime-only presentation plumbing; not serialized.
    wait_display_source: "Agent | None" = field(
        default=None,
        compare=False,
        repr=False,
    )

    # Retry-chain lineage (spawn-on-retry).
    # retry_of_timestamp: backward pointer to the immediate parent in the
    #   retry chain. None when this is not a retry.
    # retry_attempt: 0 = chain root; 1+ = retry attempt depth.
    # retry_chain_root_timestamp: short-circuit pointer to the chain root.
    # retried_as_timestamp: forward pointer to the downstream child that took
    #   over; when set the parent displays as "FAILED (RETRIED)".
    # retry_terminal: marks the parent as terminal-but-handed-off.
    # retry_error_category: one of "context_overflow", "rate_limit",
    #   "transient", "other".
    # retry_chain_siblings: direct retry children (populated at load time,
    #   not serialized). Mirrors followup_agents for the retry-chain dimension.
    retry_of_timestamp: str | None = None
    retry_attempt: int = 0
    retry_chain_root_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_terminal: bool = False
    retry_error_category: str | None = None
    retry_chain_siblings: list["Agent"] = field(default_factory=list)

    # When plans were submitted for review (one per proposal; plan agents only)
    plan_times: list[datetime] = field(default_factory=list)
    # When the coder agent was launched after plan approval (plan agents only)
    code_time: datetime | None = None
    # When the epic follow-up was launched after epic approval (plan agents only)
    epic_time: datetime | None = None
    # When feedback was submitted on the plan (one per feedback round)
    feedback_times: list[datetime] = field(default_factory=list)
    # Rejected plan path for each feedback timestamp, when known.
    feedback_plan_paths: dict[datetime, str] = field(default_factory=dict)
    # When the agent submitted questions for user review (one per round)
    questions_times: list[datetime] = field(default_factory=list)
    # Latest question request/response metadata recorded by the question flow.
    question_request_path: str | None = None
    question_response_path: str | None = None
    question_session_id: str | None = None
    # When retry attempts started (one per retry/fallback)
    retry_times: list[datetime] = field(default_factory=list)

    # Prior-attempt records loaded from artifacts_dir/attempts/ (populated at
    # load time, not serialized in bundle dicts).
    attempt_history: list[AttemptRecord] = field(default_factory=list)

    # Display-only logical project name resolved from ProjectSpec PROJECT_NAME.
    # The project_file path remains the storage identity for grouping/actions.
    project_display_name: str | None = field(default=None, compare=False)

    # Internal source marker for dismissed bundles loaded only for revive.
    _loaded_from_dismissed_bundle: bool = field(
        default=False, compare=False, repr=False
    )

    # On-disk path of the dismissed bundle file this agent was loaded from.
    # Populated alongside ``_loaded_from_dismissed_bundle`` by the dismissed
    # bundle loader so the revive audit log can record which file was deleted.
    _dismissed_bundle_path: str | None = field(default=None, compare=False, repr=False)

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
        instead of the ChangeSpec name, since that's what the user cares about.
        """
        if (
            self.agent_type == AgentType.WORKFLOW
            and not self.appears_as_agent
            and not self.is_workflow_child
            and self.workflow
        ):
            return self.workflow
        if self.is_project_agent and self.project_display_name:
            return self.project_display_name
        return humanize_cl_name(self.cl_name)

    @property
    def display_label(self) -> str:
        """Combined label for list display: Type + name."""
        return f"[{self.display_type}] {self.display_name}"

    @property
    def display_status(self) -> str:
        """Presentation status label, keeping ``status`` semantic."""
        if self.status == "RUNNING" and self.custom_role_label:
            return self.custom_role_label
        if self.status == "DONE" and self.custom_role_done_label:
            return self.custom_role_done_label
        return self.status

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

        - START is the launch/artifact timestamp for agents that did not wait
        - WAIT replaces START once an agent enters a pre-run wait phase
        - RUN is the actual execution timestamp when known
        - DONE shown for completed agents
        """
        parts: list[str] = []
        fmt = "%Y-%m-%d %H:%M:%S"
        # Pad tag to 5 chars so timestamps align.
        tag_width = 5

        def _fmt(tag: str, ts: str, extra: str | None = None) -> str:
            line = f"{tag.ljust(tag_width)} | {ts}"
            if extra:
                line += f" | {extra}"
            return line

        first_tag = (
            "WAIT"
            if self.wait_start_time is not None or self.status == "WAITING"
            else "START"
        )
        first_time = self.wait_start_time or self.start_time
        parts.append(
            _fmt(first_tag, first_time.strftime(fmt) if first_time else "Unknown")
        )
        if self.run_start_time is not None:
            parts.append(_fmt("RUN", self.run_start_time.strftime(fmt)))

        # Collect remaining timestamps and sort chronologically
        middle: list[tuple[datetime, str]] = []
        for pt in self.plan_times:
            middle.append((pt, "PLAN"))
        for ft in self.feedback_times:
            middle.append((ft, "FBACK"))
        for qt in self.questions_times:
            middle.append((qt, "QUEST"))
        for rt in self.retry_times:
            middle.append((rt, "RETRY"))
        if self.code_time is not None:
            middle.append((self.code_time, "CODE"))
        if self.epic_time is not None:
            middle.append((self.epic_time, "EPIC"))
        middle.sort(key=lambda t: t[0])
        for ts, tag in middle:
            extra = None
            if tag == "FBACK":
                path = self.feedback_plan_paths.get(ts)
                if path:
                    extra = shorten_path(path)
            parts.append(_fmt(tag, ts.strftime(fmt), extra))

        if self.stop_time is not None:
            parts.append(_fmt("DONE", self.stop_time.strftime(fmt)))

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
    def start_time_compact(self) -> str:
        """Compact formatted start time (e.g. 'Apr 12 20:25') for sidebar use."""
        if self.start_time is None:
            return "?"
        return self.start_time.strftime("%b %d %H:%M")

    @property
    def duration_display(self) -> str:
        """Display how long the agent has been running."""
        if self.start_time is None:
            return "?"
        end = self.stop_time or local_now()
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
    def is_retry_attempt(self) -> bool:
        """True when this agent is a retry of an earlier failed attempt."""
        return self.retry_attempt > 0

    @property
    def is_retried_parent(self) -> bool:
        """True when this agent failed but was retried by a downstream child."""
        return self.retried_as_timestamp is not None

    @property
    def child_linkage(self) -> AgentChildLinkage:
        """Classify this row's parent linkage.

        Workflow steps carry ``parent_workflow`` and render as workflow
        children. Family members/follow-ups carry only ``parent_timestamp`` and
        render under the parent agent without being workflow steps.
        """
        if self.parent_workflow is not None:
            return AgentChildLinkage.WORKFLOW_STEP
        if self.parent_timestamp is not None:
            return AgentChildLinkage.FAMILY_MEMBER
        return AgentChildLinkage.ROOT

    @property
    def is_child_row(self) -> bool:
        """True when this row is any kind of child in the Agents tab."""
        return self.child_linkage is not AgentChildLinkage.ROOT

    @property
    def is_workflow_step_child(self) -> bool:
        """True when this row is a child step of a workflow row."""
        return self.child_linkage is AgentChildLinkage.WORKFLOW_STEP

    @property
    def is_family_member_child(self) -> bool:
        """True when this row is a family/follow-up child row."""
        return self.child_linkage is AgentChildLinkage.FAMILY_MEMBER

    @property
    def is_workflow_child(self) -> bool:
        """Historical alias for rows folded under another row.

        This remains true for both workflow-step children and family-member
        children so existing fold/navigation behavior is preserved. New code
        that needs the child kind should use :attr:`child_linkage`.
        """
        return self.is_child_row

    @property
    def is_agent_entry(self) -> bool:
        """Check if this entry represents an agent process (with tools support).

        Agent entries run an LLM agent and may have tool-call artifacts:
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

    # --- Delegated to agent_artifacts module ---

    def get_artifacts_dir(self) -> str | None:
        """Get the artifacts directory path for this agent."""
        from sase.ace.tui.models.agent_artifacts import get_artifacts_dir

        return get_artifacts_dir(self)

    def extract_artifacts_timestamp(self) -> str | None:
        """Extract and convert timestamp from raw_suffix to artifacts format."""
        from sase.ace.tui.models.agent_artifacts import extract_artifacts_timestamp

        return extract_artifacts_timestamp(self)

    def get_raw_xprompt_content(self) -> str | None:
        """Get the raw xprompt content (before preprocessing/expansion)."""
        from sase.ace.tui.models.agent_artifacts import get_raw_xprompt_content

        return get_raw_xprompt_content(self)

    def get_live_reply_content(self) -> str | None:
        """Get the live reply content for running agents."""
        from sase.ace.tui.models.agent_artifacts import get_live_reply_content

        return get_live_reply_content(self)

    def get_timestamped_reply_chunks(self) -> list[tuple[str, str]] | None:
        """Load live reply split into timestamped chunks."""
        from sase.ace.tui.models.agent_artifacts import get_timestamped_reply_chunks

        return get_timestamped_reply_chunks(self)

    def get_response_content(self) -> str | None:
        """Get the response content for DONE agents."""
        from sase.ace.tui.models.agent_artifacts import get_response_content

        return get_response_content(self)

    def get_chat_response_content(self) -> str | None:
        """Get response content from agent_meta.json chat_path."""
        from sase.ace.tui.models.agent_artifacts import get_chat_response_content

        return get_chat_response_content(self)

    # --- Delegated to agent_bundle module ---

    def to_bundle_dict(self) -> dict[str, Any]:
        """Serialize this Agent to a dict for bundle persistence."""
        from sase.ace.tui.models.agent_bundle import to_bundle_dict

        return to_bundle_dict(self)

    @staticmethod
    def from_bundle_dict(data: dict[str, Any]) -> "Agent":
        """Reconstruct an Agent from a bundle dict."""
        from sase.ace.tui.models.agent_bundle import from_bundle_dict

        return from_bundle_dict(data)
