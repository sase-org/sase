"""Pure section aggregation for synthetic agent-clan detail panels.

The functions in this module operate only on fields already loaded on
``Agent`` rows.  They deliberately do not resolve artifact directories, stat
paths, or read files, which keeps the collapsed clan panel safe to build on
the Textual event loop.  Disk-backed enrichment lives in the prompt-panel
worker layer and is merged into :class:`ClanSectionSnapshot` later.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sase.agent.status_buckets import status_bucket_for_values

from ._agent_clan import clan_members
from .agent import Agent
from .agent_types import AgentType

if TYPE_CHECKING:
    from sase.ace.tui.tools import SlowToolSource
    from sase.ace.tui.tools.slow import SlowToolCall

    from ..widgets.prompt_panel._agent_display_state import DetailHeaderSummary


type ClanAgentIdentity = tuple[AgentType, str, str | None]
type ClanDiskSection = Literal[
    "replies",
    "context",
    "slow-tool-calls",
    "prompts",
]
CLAN_DISK_SECTIONS: frozenset[ClanDiskSection] = frozenset(
    {"replies", "context", "slow-tool-calls", "prompts"}
)
CLAN_CONTEXT_LANE_ORDER = (
    "BEAD",
    "PLAN",
    "ARTIFACTS",
    "MEMORY",
    "SKILLS",
    "WORKSPACES",
)

_SPECIAL_META_KEYS = frozenset({"meta_project", "meta_changespec", "meta_workspace"})
_COMMIT_META_KEYS = frozenset(
    {"meta_commit_message", "meta_new_commit", "meta_commit_cwd", "meta_commits"}
)


@dataclass(frozen=True, slots=True)
class ClanMemberDigest:
    """Immutable in-memory facts used by the MEMBERS aggregate."""

    identity: ClanAgentIdentity
    label: str
    status: str
    model: str | None
    family_depth: int
    family_name: str | None
    activity: str | None
    waiting: tuple[str, ...]
    retry: tuple[str, ...]
    workspace_num: int | None
    start_time: datetime | None
    run_start_time: datetime | None
    stop_time: datetime | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ClanErrorEntry:
    """One failed clan member's in-memory error details."""

    member_identity: ClanAgentIdentity
    member_label: str
    preview: str
    message: str
    traceback: str | None


@dataclass(frozen=True, slots=True)
class ClanVariableEntry:
    """One output or workflow variable attributed to its producing member."""

    member_identity: ClanAgentIdentity
    member_label: str
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class _ClanHeadingCounts:
    """Counts that are safe to show without touching disk."""

    members: int
    errors: int
    output_variables: int
    workflow_variables: int

    def for_section(self, section_id: str) -> int | None:
        """Return a known in-memory count for ``section_id`` when available."""
        return {
            "members": self.members,
            "errors": self.errors,
            "output-variables": self.output_variables,
            "workflow-variables": self.workflow_variables,
        }.get(section_id)


@dataclass(frozen=True, slots=True)
class ClanInMemorySnapshot:
    """Complete pure aggregate derived from a clan container's loaded rows."""

    clan_identity: ClanAgentIdentity
    members: tuple[ClanMemberDigest, ...]
    errors: tuple[ClanErrorEntry, ...]
    output_variables: tuple[ClanVariableEntry, ...]
    workflow_variables: tuple[ClanVariableEntry, ...]
    bead_ids: tuple[str, ...]
    plan_paths: tuple[str, ...]
    workspace_numbers: tuple[int, ...]
    heading_counts: _ClanHeadingCounts

    @property
    def member_identities(self) -> tuple[ClanAgentIdentity, ...]:
        """Return the ordered real-row identities represented by this snapshot."""
        return tuple(member.identity for member in self.members)


@dataclass(frozen=True, slots=True)
class ClanTextEntry:
    """One disk-backed reply or prompt body plus its bounded preview."""

    member_identity: ClanAgentIdentity
    member_label: str
    kind: str
    preview: str
    body: str


@dataclass(frozen=True, slots=True)
class ClanContextEntry:
    """One de-duplicated SASE-context item across one or more members."""

    key: str
    label: str
    member_labels: tuple[str, ...]
    count: int = 1
    values: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class ClanContextLane:
    """One context lane in the established SASE-context narrative order."""

    label: str
    entries: tuple[ClanContextEntry, ...]


@dataclass(frozen=True, slots=True)
class ClanSlowToolEntry:
    """One slow call attributed to its clan member."""

    member_identity: ClanAgentIdentity
    member_label: str
    source_label: str | None
    call: SlowToolCall


@dataclass(frozen=True, slots=True)
class ClanDiskMemberSnapshot:
    """Disk-backed content loaded for one real clan row."""

    member_identity: ClanAgentIdentity
    member_label: str
    loaded_sections: frozenset[ClanDiskSection]
    replies: tuple[ClanTextEntry, ...] = ()
    prompts: tuple[ClanTextEntry, ...] = ()
    context: DetailHeaderSummary | None = None
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None


@dataclass(frozen=True, slots=True)
class ClanDiskSnapshot:
    """Aggregated disk-backed content ready for fold-aware rendering."""

    loaded_sections: frozenset[ClanDiskSection]
    members: tuple[ClanDiskMemberSnapshot, ...]
    replies: tuple[ClanTextEntry, ...]
    prompts: tuple[ClanTextEntry, ...]
    context_lanes: tuple[ClanContextLane, ...]
    slow_tool_calls: tuple[ClanSlowToolEntry, ...]


@dataclass(frozen=True, slots=True)
class ClanSectionSnapshot:
    """Single renderer-facing snapshot combining pure and enriched content."""

    in_memory: ClanInMemorySnapshot
    disk: ClanDiskSnapshot | None = None
    loading_sections: frozenset[ClanDiskSection] = frozenset()


def clan_section_member_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return every real clan row, including members nested in families.

    Direct clan members retain launch order.  Sequential family descendants
    follow their family root in launch order.  Identity de-duplication handles
    compatibility fixtures that expose the same row through more than one
    runtime-child collection.
    """
    ordered: list[Agent] = []
    seen: set[ClanAgentIdentity] = set()

    def append_row(row: Agent) -> None:
        if row.is_clan_container or row.identity in seen:
            return
        seen.add(row.identity)
        ordered.append(row)
        children = tuple(
            child
            for child in row.runtime_children
            if child.is_family_member_child and not child.agent_family_parallel
        )
        for child in sorted(children, key=_member_sort_key):
            append_row(child)

    for member in sorted(clan_members(agent), key=_member_sort_key):
        append_row(member)
    return tuple(ordered)


def aggregate_clan_in_memory(agent: Agent) -> ClanInMemorySnapshot:
    """Build the clan aggregation layer without filesystem access."""
    rows = clan_section_member_rows(agent)
    clan_name = agent.agent_clan or agent.display_name
    members = tuple(
        build_agent_member_digest(
            row,
            label=_clan_relative_label(row, clan_name),
            family_depth=_family_depth(row),
        )
        for row in rows
    )
    label_by_identity = {member.identity: member.label for member in members}
    errors = aggregate_agent_errors(rows, labels=label_by_identity)
    output_variables = aggregate_agent_output_variables(
        rows,
        labels=label_by_identity,
    )
    workflow_variables = aggregate_agent_workflow_variables(
        rows,
        labels=label_by_identity,
    )
    bead_ids = _ordered_unique(
        bead_id
        for row in rows
        for bead_id in (row.epic_bead_id, row.phase_bead_id)
        if bead_id
    )
    plan_paths = _ordered_unique(
        path for row in rows for path in _in_memory_plan_paths(row) if path
    )
    workspace_numbers = tuple(
        sorted(
            {
                workspace_num
                for row in rows
                if (workspace_num := row.effective_workspace_num) is not None
            }
        )
    )
    counts = _ClanHeadingCounts(
        members=len(members),
        errors=len(errors),
        output_variables=len(output_variables),
        workflow_variables=len(workflow_variables),
    )
    return ClanInMemorySnapshot(
        clan_identity=agent.identity,
        members=members,
        errors=errors,
        output_variables=output_variables,
        workflow_variables=workflow_variables,
        bead_ids=bead_ids,
        plan_paths=plan_paths,
        workspace_numbers=workspace_numbers,
        heading_counts=counts,
    )


def _in_memory_plan_paths(agent: Agent) -> tuple[str, ...]:
    """Return only plan paths safe to classify without deferred enrichment.

    Phase rows need parent-bead resolution before their overloaded historical
    paths can be classified, so the worker contributes those PLAN entries.
    This keeps a parent epic roadmap from appearing as a phase-authored PLAN.
    """
    if agent.phase_bead_id or agent.agent_family_role == "phase":
        return ()
    return tuple(
        path
        for path in (agent.plan_path, agent.archived_plan_path, agent.sdd_plan_path)
        if path
    )


def aggregate_agent_errors(
    rows: tuple[Agent, ...],
    *,
    labels: dict[ClanAgentIdentity, str] | None = None,
) -> tuple[ClanErrorEntry, ...]:
    """Return deterministic error entries for arbitrary loaded agent rows."""
    entries: list[ClanErrorEntry] = []
    for row in rows:
        failed = status_bucket_for_values(row.status) == "Failed"
        if not row.error_message and not failed:
            continue
        message = row.error_message or "Runner failed without error details."
        entries.append(
            ClanErrorEntry(
                member_identity=row.identity,
                member_label=(labels or {}).get(row.identity, _row_name(row)),
                preview=first_meaningful_line(message),
                message=message,
                traceback=row.error_traceback,
            )
        )
    return tuple(entries)


def aggregate_agent_output_variables(
    rows: tuple[Agent, ...],
    *,
    labels: dict[ClanAgentIdentity, str] | None = None,
) -> tuple[ClanVariableEntry, ...]:
    """Return every output variable in row order and sorted key order."""
    entries: list[ClanVariableEntry] = []
    for row in rows:
        label = (labels or {}).get(row.identity, _row_name(row))
        for name in sorted(row.output_variables):
            entries.append(
                ClanVariableEntry(
                    member_identity=row.identity,
                    member_label=label,
                    name=name,
                    value=row.output_variables[name],
                )
            )
    return tuple(entries)


def aggregate_agent_workflow_variables(
    rows: tuple[Agent, ...],
    *,
    labels: dict[ClanAgentIdentity, str] | None = None,
) -> tuple[ClanVariableEntry, ...]:
    """Return non-structural ``meta_*`` workflow outputs from member rows."""
    entries: list[ClanVariableEntry] = []
    for row in rows:
        if not isinstance(row.step_output, dict):
            continue
        label = (labels or {}).get(row.identity, _row_name(row))
        for key in sorted(row.step_output):
            if (
                not key.startswith("meta_")
                or key in _SPECIAL_META_KEYS
                or key in _COMMIT_META_KEYS
            ):
                continue
            entries.append(
                ClanVariableEntry(
                    member_identity=row.identity,
                    member_label=label,
                    name=_format_meta_key(key),
                    value=str(row.step_output[key]),
                )
            )
    return tuple(entries)


def first_meaningful_line(content: str, *, max_chars: int = 120) -> str:
    """Return a whitespace-normalized, bounded first non-empty line."""
    if max_chars < 1:
        return ""
    for raw_line in content.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if len(line) <= max_chars:
            return line
        if max_chars == 1:
            return "…"
        return line[: max_chars - 1].rstrip() + "…"
    return ""


def build_agent_member_digest(
    row: Agent,
    *,
    label: str,
    family_depth: int,
) -> ClanMemberDigest:
    """Project one loaded row into the shared in-memory roster digest."""
    return ClanMemberDigest(
        identity=row.identity,
        label=label,
        status=row.display_status,
        model=row.model,
        family_depth=family_depth,
        family_name=row.agent_family,
        activity=row.activity,
        waiting=_waiting_digest(row),
        retry=_retry_digest(row),
        workspace_num=row.effective_workspace_num,
        start_time=row.start_time,
        run_start_time=row.run_start_time,
        stop_time=row.stop_time,
        attempt_count=len(row.attempt_history),
    )


def _waiting_digest(row: Agent) -> tuple[str, ...]:
    parts: list[str] = []
    if row.waiting_for:
        parts.append("for " + ", ".join(row.waiting_for))
    if row.waiting_for_beads:
        parts.append("for beads " + ", ".join(row.waiting_for_beads))
    if row.wait_duration is not None:
        parts.append(f"{row.wait_duration:g}s")
    if row.wait_until:
        parts.append(f"until {row.wait_until}")
    if row.wait_runners is not None:
        parts.append(f"runners≤{row.wait_runners}")
    if row.runner_slot_queue_position is not None:
        queue = f"queue #{row.runner_slot_queue_position}"
        if row.runner_slot_queue_size is not None:
            queue += f"/{row.runner_slot_queue_size}"
        parts.append(queue)
    return tuple(parts)


def _retry_digest(row: Agent) -> tuple[str, ...]:
    parts: list[str] = []
    if row.retry_count or row.max_retries:
        parts.append(f"{row.retry_count}/{row.max_retries}")
    if row.retry_status:
        parts.append(row.retry_status.replace("_", " "))
    if row.using_fallback:
        fallback = row.fallback_model or "fallback"
        parts.append(f"via {fallback}")
    if row.attempt_history:
        parts.append(
            f"{len(row.attempt_history)} attempt"
            f"{'s' if len(row.attempt_history) != 1 else ''}"
        )
    return tuple(parts)


def _family_depth(row: Agent) -> int:
    return 1 if row.is_family_member_child and not row.agent_family_parallel else 0


def _member_sort_key(row: Agent) -> tuple[bool, str, str]:
    return (
        row.start_time is None,
        row.start_time.isoformat() if row.start_time is not None else "",
        _row_name(row),
    )


def _row_name(row: Agent) -> str:
    return row.presented_agent_name or row.step_name or row.display_name


def _clan_relative_label(row: Agent, clan_name: str) -> str:
    name = _row_name(row)
    prefix = f"{clan_name}."
    if name.startswith(prefix):
        return name[len(clan_name) :]
    return name


def _format_meta_key(key: str) -> str:
    return key.removeprefix("meta_").replace("_", " ").title()


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "CLAN_CONTEXT_LANE_ORDER",
    "CLAN_DISK_SECTIONS",
    "ClanAgentIdentity",
    "ClanContextEntry",
    "ClanContextLane",
    "ClanDiskMemberSnapshot",
    "ClanDiskSection",
    "ClanDiskSnapshot",
    "ClanErrorEntry",
    "ClanInMemorySnapshot",
    "ClanMemberDigest",
    "ClanSectionSnapshot",
    "ClanSlowToolEntry",
    "ClanTextEntry",
    "ClanVariableEntry",
    "aggregate_agent_errors",
    "aggregate_agent_output_variables",
    "aggregate_agent_workflow_variables",
    "aggregate_clan_in_memory",
    "build_agent_member_digest",
    "clan_section_member_rows",
    "first_meaningful_line",
]
