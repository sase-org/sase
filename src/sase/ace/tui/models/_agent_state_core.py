"""Core identity and status fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import datetime

from .agent_types import AgentType


@dataclass
class AgentStateCoreFields:
    """Identity, status, and type-specific fields stored for a single agent row."""

    agent_type: AgentType
    cl_name: str  # Patch name
    project_file: str  # Path to project spec file
    status: str  # "RUNNING", etc.
    start_time: datetime | None  # Parsed from timestamp suffix
    status_bucket: str | None = None  # Optional explicit display bucket override
    run_start_time: datetime | None = (
        None  # When agent actually started running (after waiting)
    )
    wait_start_time: datetime | None = None  # Launch timestamp for waited agents
    stop_time: datetime | None = None  # When agent completed (DONE/FAILED)

    # Type-specific fields
    workspace_num: int | None = None  # For RUNNING type
    workflow: str | None = None  # For RUNNING type (e.g., "crs")
    hook_command: str | None = None  # For hook-based agents
    stitch_id: str | None = None  # For hook-based agents
    commit_entry_id: InitVar[str | None] = None  # legacy compatibility alias
    mentor_profile: str | None = None  # For mentor agents
    mentor_name: str | None = None  # For mentor agents
    reviewer: str | None = None  # For CRS agents (e.g., "critique")

    # PID for process management
    pid: int | None = None

    # Runtime-only proof that this row is backed by a runner whose PID was
    # verified live. The visible status is intentionally not authoritative:
    # agent session normalization may replace RUNNING with semantic or failed child
    # states while the outer runner is still alive and waiting to retry.
    runner_is_live: bool = field(default=False, compare=False, repr=False)

    # For agent suffix parsing
    raw_suffix: str | None = None

    # Response file path for completed agents
    response_path: str | None = None

    # Diff file path for completed agents
    diff_path: str | None = None

    # Precomputed badge classification for ``diff_path``. None means the row
    # has not gone through the deferred background classification pass yet
    # (see ``AgentDiffBadgeMixin``); the loader pass leaves it unset.
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
