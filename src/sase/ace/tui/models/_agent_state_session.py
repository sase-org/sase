"""Agent-session, clan, timing, and linkage fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sase.core.output_variable_values import VarValue

from .agent_attempt import AttemptRecord

if TYPE_CHECKING:
    from sase.core.agent_identity_facade import AgentOwnerIdentity
    from sase.core.agent_scan_wire import AgentClanContextWire

    from .agent import Agent


@dataclass
class AgentStateSessionFields:
    """Archive, session, clan, timing, and linkage state for one agent row."""

    # Immutable archive provenance and persisted capabilities. Live rows
    # default to restartable so existing prompt-based actions keep their
    # current behavior unless a loaded archive record says otherwise.
    source_username: str | None = None
    source_machine: str | None = None
    source_run_id: str | None = None
    archive_visibility: str = "visible"
    archive_payload_sha256: str | None = None
    archive_capabilities: dict[str, Any] | None = None
    historically_viewable: bool = True
    durably_revivable: bool = True
    restartable: bool = True
    missing_requirements: list[str] = field(default_factory=list)

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
    # %auto:epic, or the Agents-tab `A` toggle). Stays True in memory for tale/epic
    # — it drives the ⚡ row icon — even though the persisted ``approve`` key is
    # omitted for those (the action below carries the kind).
    approve: bool = False

    # Explicit plan auto-approval action: "tale" or "epic" (None means a normal
    # plan approval). Renders as the ⚡T / ⚡E row-icon suffix.
    auto_approve_plan_action: str | None = None

    # The plan action chosen at approval time, e.g. "tale", "epic", "commit".
    # Persisted in agent_meta.json so the parent's approved-status
    # variant can be reconstructed across `sase tui` restart even after the
    # workflow itself has completed.
    plan_action: str | None = None

    # Role suffix annotation (e.g., ".plan", ".code", ".q") for follow-up agents
    role_suffix: str | None = None

    # Agent-session metadata for plan/question/feedback/coder handoff flows.
    agent_session: str | None = None
    agent_session_role: str | None = None
    imported_source_owner: AgentOwnerIdentity | None = None
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
    is_imported_agent_session_container: bool = field(default=False, compare=False)
    is_remote_agent_session_container: bool = field(default=False, compare=False)
    tree_parent_key: str | None = field(default=None, compare=False)
    tree_depth: int = field(default=0, compare=False)
    clan_tribes: tuple[str, ...] = field(default_factory=tuple, compare=False)
    # Explicitly marks execution-neutral parallel-agent-session membership. Unlike
    # serial plan-chain linkage, these children own independent processes and
    # must be included when their session root is killed or dismissed.
    agent_session_parallel: bool = False
    plan_chain_root: bool = False

    # User-managed tribe (no '@' prefix; at most one per agent).
    # Populated from ``~/.sase/agent_tribes.json`` after agents are loaded.
    tribe: str | None = None

    # Presentation-root tab placement (stored canonical name, None for main).
    agent_tab: str | None = None

    # Agent-scoped output variables written by ``sase var set``.
    output_variables: dict[str, VarValue] = field(default_factory=dict)

    # Follow-up agents linked to this parent (populated at load time, not serialized)
    followup_agents: list[Agent] = field(default_factory=list)

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

    # Member row whose status this synthetic container mirrors (a clan's lone
    # running member). Runtime-only presentation plumbing; not serialized.
    status_display_source: Agent | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    # Session container row whose SESSION TURNS roster lists this row. Runtime
    # presentation plumbing; not serialized. ``compare``/``repr`` must stay off:
    # this pointer closes a cycle with ``followup_agents``/``runtime_children``
    # and dataclass eq/repr (and the repr-based hint digest) would recurse.
    agent_session_container: Agent | None = field(
        default=None, compare=False, repr=False
    )
    imported_agent_session_parent_synthetic: bool = field(
        default=False, compare=False, repr=False
    )

    # Set when a session root's members reveal a plan chain that started after
    # the root was promoted. Derived during status normalization; not
    # serialized. Sticky: normalization only ever sets this, never clears it.
    derived_plan_agent_session_root: bool = field(
        default=False, compare=False, repr=False
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
    # Remote rows ship the derived answered signal instead of the response path.
    question_answered: bool = False
    question_session_id: str | None = None
    # When retry attempts started (one per retry/fallback)
    retry_times: list[datetime] = field(default_factory=list)

    # Prior-attempt records loaded from artifacts_dir/attempts/ (populated at
    # load time, not serialized in bundle dicts).
    attempt_history: list[AttemptRecord] = field(default_factory=list)

    # Display-only logical project name resolved from ProjectSpec PROJECT_NAME.
    # The project_file path remains the storage identity for grouping/actions.
    project_display_name: str | None = field(default=None, compare=False)
