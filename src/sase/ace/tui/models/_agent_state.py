"""Dataclass state fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sase.core.output_variable_values import VarValue

from .agent_attempt import AttemptRecord
from .agent_types import AgentType, LinkedRepoMetadata

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentClanContextWire

    from .agent import Agent


@dataclass
class AgentState:
    """Mutable state stored for a single agent row."""

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
    # family normalization may replace RUNNING with semantic or failed child
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

    # Canonical plan association for detail-header enrichment. The source
    # references are retained so approval changes can switch between the
    # durable local archive and the committed SDD copy without re-reading
    # marker files on the render path.
    plan_path: str | None = None
    archived_plan_path: str | None = None
    sdd_plan_path: str | None = None
    plan_committed: bool | None = None

    # Parent-epic identity is independent from the phase agent's authored plan.
    # Older rows overloaded ``sdd_plan_path``; deferred enrichment recovers
    # their parent relationship from the local bead association instead.
    epic_plan_ref: str | None = None
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
    # work is still running (for example Markdown PDF construction). The
    # prompt/detail header renders this as a labeled Activity field.
    activity: str | None = None

    # Monitor-member projection. Monitor rows are ordinary agent-family
    # members whose work is one supervised OS command rather than an LLM turn.
    monitor_id: str | None = None
    monitor_state: str | None = None
    monitor_command: str | None = None
    monitor_label: str | None = None
    monitor_exit_code: int | None = None

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

    # Bare launch-time alias recorded when %model:@<alias> was used. Rendered
    # as a provenance chip and never re-resolved at display time.
    model_alias: str | None = None

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

    # Agent name assigned via %id directive or manual TUI naming
    agent_name: str | None = None

    # Precomputed name used by the Agents-tab row annotation and detail header.
    # Family root rows present the bare container name while retaining their
    # concrete persisted member name in ``agent_name``.
    presented_agent_name: str | None = field(
        default=None,
        init=False,
        compare=False,
    )

    # Precomputed identity used for hood/neighbor relationships. Unlike
    # ``presented_agent_name``, this retains a concrete family member suffix;
    # only explicit prefixes belonging to the selected current owner are
    # removed during snapshot normalization.
    presented_identity_name: str | None = field(
        default=None,
        init=False,
        compare=False,
    )

    # Names this agent is waiting for (from %wait directives)
    waiting_for: list[str] = field(default_factory=list)

    # Bead IDs this agent is waiting to reach closed status.
    waiting_for_beads: list[str] = field(default_factory=list)

    # Duration wait in seconds (from %wait(time=5m) directive)
    wait_duration: float | None = None

    # Absolute time wait target as ISO 8601 string (from %wait(time=1430) directive)
    wait_until: str | None = None

    # Runner-slot wait metadata projected from waiting.json. ``wait_runners``
    # is the existing-runner threshold; config-gated waits render the total
    # cap as threshold + 1, while explicit %wait(runners=N) waits render N.
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    wait_priority: int | None = None
    wait_priority_explicit: bool = False
    slot_requested_at: str | None = None

    # Snapshot-derived display context. These values are recomputed from the
    # already-loaded Agents refresh payload after full and artifact-delta
    # merges; rendering them never triggers another filesystem scan. Queue
    # position and size cover every live slot waiter in capacity-aware display
    # order, even while the runner pool is full.
    runner_slots_in_use: int | None = None
    runner_slot_queue_position: int | None = None
    runner_slot_queue_size: int | None = None

    # True while this row's own pending_question.json marker exists. Root rows
    # with this flag have yielded their runner slot; family status propagation
    # must not be used as a substitute because a child question remains exempt.
    runner_slot_yielded: bool = False

    # Explicit artifacts directory path (for workflow steps loaded from marker files)
    artifacts_dir: str | None = None

    # Embedded workflow name for steps within embedded workflows
    # (e.g., "git", "propose")
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

    # Whether this agent was loaded from a Patch field (HOOKS/MENTORS/COMMENTS)
    _from_patch: bool = False

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
    # Rootless parallel clan membership. Clan names are containers and never
    # identify a real agent row.
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    clan_summary: str | None = None
    # Snapshot-only semantic context. It is never persisted back to artifacts
    # or dismissed bundles and may originate from an omitted declaration row.
    clan_context: AgentClanContextWire | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    # Agents-tab-only tree projection. Clan containers are synthetic rows;
    # ``tree_parent_key`` and ``tree_depth`` place their loaded members below
    # them without overloading artifact ``parent_timestamp`` relationships.
    is_clan_container: bool = field(default=False, compare=False)
    tree_parent_key: str | None = field(default=None, compare=False)
    tree_depth: int = field(default=0, compare=False)
    clan_tribes: tuple[str, ...] = field(default_factory=tuple, compare=False)
    # Explicitly marks execution-neutral parallel family membership. Unlike
    # serial plan-chain linkage, these children own independent processes and
    # must be included when their family root is killed or dismissed.
    agent_family_parallel: bool = False
    plan_chain_root: bool = False

    # User-managed tribe (no '@' prefix; at most one per agent).
    # Populated from ``~/.sase/agent_tribes.json`` after agents are loaded.
    tribe: str | None = None

    # Agent-scoped output variables written by ``sase var set``.
    output_variables: dict[str, VarValue] = field(default_factory=dict)

    # Follow-up agents linked to this parent (populated at load time, not serialized)
    followup_agents: list[Agent] = field(default_factory=list)

    # Marks the display-only planner child synthesized for a lone plan root.
    # The marker is derived during load and intentionally omitted from bundles.
    is_synthetic_planner: bool = field(default=False, init=False, compare=False)

    # Child agents whose intervals contribute to this row's aggregate runtime
    # (populated at load time, not serialized).
    runtime_children: list[Agent] = field(default_factory=list)

    # WAITING child row whose wait metadata should drive this row's display.
    # Runtime-only presentation plumbing; not serialized.
    wait_display_source: Agent | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    # Family container row whose FAMILY MEMBERS roster lists this row. Runtime
    # presentation plumbing; not serialized. ``compare``/``repr`` must stay off:
    # this pointer closes a cycle with ``followup_agents``/``runtime_children``
    # and dataclass eq/repr (and the repr-based hint digest) would recurse.
    family_container: Agent | None = field(default=None, compare=False, repr=False)

    # Set when a family root's members reveal a plan chain that started after
    # the root was promoted. Derived during status normalization; not
    # serialized. Sticky: normalization only ever sets this, never clears it.
    derived_plan_family_root: bool = field(default=False, compare=False, repr=False)

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
    retry_chain_siblings: list[Agent] = field(default_factory=list)

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


def _get_commit_entry_id(agent: AgentState) -> str | None:  # legacy compatibility alias
    return agent.stitch_id


def _set_commit_entry_id(
    agent: AgentState,
    value: str | None,
) -> None:  # legacy compatibility alias
    agent.stitch_id = value


AgentState.commit_entry_id = property(  # type: ignore[attr-defined] # legacy compatibility alias
    _get_commit_entry_id,
    _set_commit_entry_id,
)
