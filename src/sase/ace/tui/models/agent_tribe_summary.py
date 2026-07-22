"""Pure, in-memory presentation snapshots for Agents-tab tribe panels."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sase.agent.status_buckets import status_bucket_for_values
from ._agent_clan import (
    agent_hole_status_counts,
    agent_status_projections,
    agent_summary_status_counts,
    aggregate_clan_status,
)
from ._agent_clan_sections import (
    ClanErrorEntry,
    ClanMemberDigest,
    ClanVariableEntry,
    aggregate_agent_errors,
    aggregate_agent_output_variables,
    aggregate_agent_workflow_variables,
    build_agent_member_digest,
    clan_section_member_rows,
    first_meaningful_line,
)
from ._agent_tree import agent_is_tree_child
from .agent import Agent, AgentType, compute_row_runtime
from .agent_family_members import (
    concrete_family_member_rows,
    is_sequential_family_container,
)
from .agent_panels import PanelKey, agent_panel_label
from . import agent_time


type AgentIdentity = tuple[AgentType, str, str | None]
type TribePanelIdentity = tuple[Literal["panel"], PanelKey]


@dataclass(frozen=True, slots=True)
class AgentPanelFocus:
    """Identity and rendered state of the whole panel that owns focus."""

    panel_key: PanelKey
    collapsed: bool

    @property
    def container_identity(self) -> TribePanelIdentity:
        """Return the roster registry identity for this tribe panel."""
        return _tribe_panel_identity(self.panel_key)


@dataclass(frozen=True, slots=True)
class CollapsedAgentPanelFocus(AgentPanelFocus):
    """Compatibility focus value for callers limited to collapsed panels."""

    collapsed: bool = True


@dataclass(frozen=True, slots=True)
class TribeStatusCounts:
    """Status-count projection shared by tribe headers and unit chips."""

    stopped: int = 0
    running: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class _TribeUnitChild:
    """One unnumbered real row nested beneath a tribe roster unit."""

    identity: AgentIdentity
    label: str
    kind: str
    status: str
    effective_bucket: str | None
    model: str
    duration: str
    digest: ClanMemberDigest
    is_marked: bool
    is_unread: bool


@dataclass(frozen=True, slots=True)
class _TribeUnitSnapshot:
    """Immutable roster data for one top-level rendered tribe unit."""

    identity: AgentIdentity
    presented_name: str
    label: str
    kind: str
    status: str
    model: str
    duration: str
    status_counts: TribeStatusCounts | None
    digest: ClanMemberDigest | None
    children: tuple[_TribeUnitChild, ...]
    is_marked: bool
    is_unread: bool


@dataclass(frozen=True, slots=True)
class TribeAttentionEntry:
    """A bounded operational triage row for one unit needing attention."""

    unit_identity: AgentIdentity
    unit_label: str
    status: str
    status_bucket: str
    preview: str


@dataclass(frozen=True, slots=True)
class AgentTribeSummarySnapshot:
    """Complete renderer-facing snapshot for one tribe metadata document."""

    panel_key: PanelKey
    container_identity: TribePanelIdentity
    label: str
    panel_collapsed: bool
    status: str
    counts: TribeStatusCounts
    clan_count: int
    family_count: int
    hole_count: int
    nested_count: int
    runtime_span: str
    units: tuple[_TribeUnitSnapshot, ...]
    attention: tuple[TribeAttentionEntry, ...]
    errors: tuple[ClanErrorEntry, ...]
    output_variables: tuple[ClanVariableEntry, ...]
    workflow_variables: tuple[ClanVariableEntry, ...]


def _tribe_panel_identity(panel_key: PanelKey) -> TribePanelIdentity:
    """Return a stable, hashable container identity for a tribe panel."""
    return ("panel", panel_key)


def _panel_label(panel_key: PanelKey) -> str:
    from .tribe_display import tribe_display_for

    label = agent_panel_label(panel_key)
    icon = tribe_display_for(panel_key).icon
    return f"{icon} {label}" if icon else label


def _row_name(agent: Agent) -> str:
    return (
        agent.presented_agent_name
        or agent.agent_name
        or agent.step_name
        or agent.display_name
    )


def _unit_kind(agent: Agent) -> str:
    if agent.is_clan_container:
        return "clan"
    if is_sequential_family_container(agent):
        return "family"
    if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
        return "workflow"
    return "agent"


def _member_kind(agent: Agent) -> str:
    if agent.is_family_container_row:
        return "family"
    if agent.is_workflow_step_child or agent.agent_type == AgentType.WORKFLOW:
        return "step"
    return "agent"


def _descendant_rows(agent: Agent) -> tuple[Agent, ...]:
    rows: list[Agent] = []
    seen: set[AgentIdentity] = set()

    def visit(row: Agent) -> None:
        if row.is_clan_container or row.identity in seen:
            return
        seen.add(row.identity)
        rows.append(row)
        for child in (*row.runtime_children, *row.followup_agents):
            visit(child)

    for child in (*agent.runtime_children, *agent.followup_agents):
        visit(child)
    return tuple(rows)


def tribe_unit_real_rows(unit: Agent) -> tuple[Agent, ...]:
    """Return the real rows represented by one top-level tribe unit."""
    if unit.is_clan_container:
        return clan_section_member_rows(unit)
    if is_sequential_family_container(unit):
        return concrete_family_member_rows(unit)
    return _dedupe_rows((unit, *_descendant_rows(unit)))


def tribe_unit_roots(agents: Sequence[Agent]) -> tuple[Agent, ...]:
    """Return top-level tribe units in their panel presentation order."""
    return tuple(agent for agent in agents if not agent_is_tree_child(agent))


def _dedupe_rows(rows: Sequence[Agent]) -> tuple[Agent, ...]:
    ordered: list[Agent] = []
    seen: set[AgentIdentity] = set()
    for row in rows:
        if row.identity in seen:
            continue
        seen.add(row.identity)
        ordered.append(row)
    return tuple(ordered)


def _relative_child_label(unit: Agent, child: Agent) -> str:
    name = _row_name(child)
    if unit.is_clan_container:
        clan_name = unit.presented_clan_reference_name() or unit.display_name
        prefix = f"{clan_name}."
        if name.startswith(prefix):
            return name[len(prefix) - 1 :]
    family_name = unit.presented_family_reference_name()
    if family_name and name.startswith(family_name) and len(name) > len(family_name):
        return name[len(family_name) :]
    return name


def _duration(agent: Agent, *, now: datetime) -> str:
    _timestamp, elapsed = compute_row_runtime(agent, now=now)
    return elapsed or "—"


def _model_label(rows: Sequence[Agent]) -> str:
    models = tuple(dict.fromkeys(row.model for row in rows if row.model))
    if not models:
        return "default"
    if len(models) == 1:
        return models[0]
    return "mixed"


def _status_counts(
    rows: Sequence[Agent],
    unread_ids: Collection[AgentIdentity],
) -> TribeStatusCounts:
    counts = agent_summary_status_counts(rows, unread_ids)
    return TribeStatusCounts(
        stopped=counts.stopped,
        running=counts.running,
        waiting=counts.waiting,
        failed=counts.failed,
        unread=counts.unread,
        done=counts.done,
    )


def _hole_status_counts(
    rows: Sequence[Agent],
    unread_ids: Collection[AgentIdentity],
) -> tuple[TribeStatusCounts, int]:
    counts = agent_hole_status_counts(rows, unread_ids)
    return (
        TribeStatusCounts(
            stopped=counts.stopped,
            running=counts.running,
            waiting=counts.waiting,
            failed=counts.failed,
            unread=counts.unread,
            done=counts.done,
        ),
        counts.total,
    )


def _unit_snapshot(
    unit: Agent,
    *,
    unread_ids: Collection[AgentIdentity],
    marked_ids: Collection[AgentIdentity],
    now: datetime,
) -> _TribeUnitSnapshot:
    rows = tribe_unit_real_rows(unit)
    nested_rows = tuple(row for row in rows if row.identity != unit.identity)
    effective_bucket_by_identity = {
        projection.agent.identity: projection.bucket
        for projection in agent_status_projections((unit,))
    }
    children = tuple(
        _TribeUnitChild(
            identity=row.identity,
            label=_relative_child_label(unit, row),
            kind=_member_kind(row),
            status=row.display_status,
            effective_bucket=effective_bucket_by_identity.get(row.identity),
            model=row.model or "default",
            duration=_duration(row, now=now),
            digest=build_agent_member_digest(
                row,
                label=_relative_child_label(unit, row),
                family_depth=1,
            ),
            is_marked=row.identity in marked_ids,
            is_unread=row.identity in unread_ids,
        )
        for row in nested_rows
    )
    root_digest = None
    if not unit.is_clan_container:
        root_digest = build_agent_member_digest(
            unit,
            label=_row_name(unit),
            family_depth=0,
        )
    return _TribeUnitSnapshot(
        identity=unit.identity,
        presented_name=_row_name(unit),
        label=_row_name(unit),
        kind=_unit_kind(unit),
        status=unit.display_status,
        model=_model_label(rows or (unit,)),
        duration=_duration(unit, now=now),
        status_counts=(
            _status_counts((unit,), unread_ids)
            if unit.is_clan_container or is_sequential_family_container(unit)
            else None
        ),
        digest=root_digest,
        children=children,
        is_marked=any(row.identity in marked_ids for row in rows)
        or (unit.identity in marked_ids),
        is_unread=any(row.identity in unread_ids for row in rows)
        or (unit.identity in unread_ids),
    )


def _attention_preview(rows: Sequence[Agent], status: str) -> str:
    for row in rows:
        preview = first_meaningful_line(row.error_message or row.activity or "")
        if preview:
            return preview
    for row in rows:
        if row.waiting_for:
            return "waiting for " + ", ".join(row.waiting_for)
        if row.waiting_for_beads:
            return "waiting for beads " + ", ".join(row.waiting_for_beads)
    return status


def _runtime_span(rows: Sequence[Agent], *, now: datetime) -> str:
    starts: list[datetime] = []
    for row in rows:
        start = row.run_start_time or row.start_time
        if start is not None:
            starts.append(start)
    if not starts:
        return "—"
    ends = [row.stop_time or now for row in rows if row.start_time is not None]
    if not ends:
        return "—"
    return agent_time.format_compact_duration((max(ends) - min(starts)).total_seconds())


def build_agent_tribe_summary_snapshot(
    panel_key: PanelKey,
    agents: Sequence[Agent],
    *,
    panel_collapsed: bool,
    unread_ids: Collection[AgentIdentity] = (),
    marked_ids: Collection[AgentIdentity] = (),
    now: datetime | None = None,
) -> AgentTribeSummarySnapshot:
    """Build a fold-independent tribe snapshot using loaded rows only."""
    reference = now or agent_time.local_now()
    roots = tribe_unit_roots(agents)
    units = tuple(
        _unit_snapshot(
            agent,
            unread_ids=unread_ids,
            marked_ids=marked_ids,
            now=reference,
        )
        for agent in roots
    )
    real_rows = _dedupe_rows(
        tuple(row for root in roots for row in tribe_unit_real_rows(root))
    )
    labels = {row.identity: _row_name(row) for row in real_rows}
    attention = tuple(
        TribeAttentionEntry(
            unit_identity=unit.identity,
            unit_label=unit.label,
            status=unit.status,
            status_bucket=status_bucket_for_values(unit.status),
            preview=_attention_preview(
                tribe_unit_real_rows(root) or (root,), unit.status
            ),
        )
        for root, unit in zip(roots, units, strict=True)
        if status_bucket_for_values(unit.status) in {"Failed", "Stopped", "Waiting"}
    )
    status = aggregate_clan_status(row.status for row in real_rows) or "EMPTY"
    family_identities = {
        row.identity for row in real_rows if is_sequential_family_container(row)
    }
    family_identities.update(unit.identity for unit in units if unit.kind == "family")
    nested_count = sum(
        len(agent_status_projections((root,)))
        if root.is_clan_container
        else sum(
            projection.agent.identity != root.identity
            for projection in agent_status_projections((root,))
        )
        if is_sequential_family_container(root)
        else 0
        for root in roots
    )
    hole_counts, hole_count = _hole_status_counts(roots, unread_ids)
    return AgentTribeSummarySnapshot(
        panel_key=panel_key,
        container_identity=_tribe_panel_identity(panel_key),
        label=_panel_label(panel_key),
        panel_collapsed=panel_collapsed,
        status=status,
        counts=hole_counts,
        clan_count=sum(unit.kind == "clan" for unit in units),
        family_count=len(family_identities),
        hole_count=hole_count,
        nested_count=nested_count,
        runtime_span=_runtime_span(real_rows, now=reference),
        units=units,
        attention=attention,
        errors=aggregate_agent_errors(real_rows, labels=labels),
        output_variables=aggregate_agent_output_variables(real_rows, labels=labels),
        workflow_variables=aggregate_agent_workflow_variables(
            real_rows,
            labels=labels,
        ),
    )


__all__ = [
    "AgentPanelFocus",
    "AgentTribeSummarySnapshot",
    "CollapsedAgentPanelFocus",
    "TribeAttentionEntry",
    "TribePanelIdentity",
    "TribeStatusCounts",
    "build_agent_tribe_summary_snapshot",
    "tribe_unit_real_rows",
    "tribe_unit_roots",
]
