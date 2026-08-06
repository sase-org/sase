"""In-memory filtering index for rows in the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from sase.bead.filter_query import BeadFilterValues
from sase.bead.plus_one_presentation import plus_one_evidence_search_text
from sase.bead.reopen_presentation import close_history_search_text

from .beads_data import BeadsSnapshot, ProjectBead
from .beads_list import BeadRowKind, row_option_id


@dataclass(frozen=True)
class _BeadFilterRecord:
    row_kind: BeadRowKind
    project: str
    project_display_name: str
    project_labels: frozenset[str]
    type_labels: frozenset[str]
    tier_labels: frozenset[str]
    status_labels: frozenset[str]
    size_labels: frozenset[str]
    has_labels: frozenset[str]
    assignee: str
    owner: str
    model: str
    timestamp: int | None
    haystack: tuple[str, ...]
    option_id: str
    bead_id: str


@dataclass(frozen=True)
class BeadFilterIndex:
    source_key: tuple[object, ...]
    records: tuple[_BeadFilterRecord, ...]
    by_option_id: Mapping[str, _BeadFilterRecord]

    def __iter__(self) -> Iterator[_BeadFilterRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)


def build_bead_filter_index(snapshot: BeadsSnapshot) -> BeadFilterIndex:
    """Build one prefolded record per bead in the loaded snapshot."""

    records = [
        *(_record(snapshot, "task", item) for item in snapshot.tasks),
        *(_record(snapshot, "epic", item) for item in snapshot.epics),
        *(
            _record(snapshot, "phase", item)
            for phases in snapshot.phases_by_epic.values()
            for item in phases
        ),
    ]
    frozen_records = tuple(records)
    return BeadFilterIndex(
        source_key=snapshot.source_key,
        records=frozen_records,
        by_option_id=MappingProxyType(
            {record.option_id: record for record in frozen_records}
        ),
    )


def compile_bead_matcher(
    values: BeadFilterValues,
) -> Callable[[_BeadFilterRecord], bool]:
    """Compile parsed bead-filter values into a cheap row predicate."""

    wanted_types = _fold_values(values.types)
    excluded_types = _fold_values(values.excluded_types)
    wanted_tiers = _fold_values(values.tiers)
    excluded_tiers = _fold_values(values.excluded_tiers)
    wanted_statuses = _fold_values(values.statuses)
    excluded_statuses = _fold_values(values.excluded_statuses)
    wanted_sizes = _fold_values(values.sizes)
    excluded_sizes = _fold_values(values.excluded_sizes)
    wanted_projects = _fold_values(values.projects)
    excluded_projects = _fold_values(values.excluded_projects)
    wanted_assignees = _fold_values(values.assignees)
    excluded_assignees = _fold_values(values.excluded_assignees)
    wanted_owners = _fold_values(values.owners)
    excluded_owners = _fold_values(values.excluded_owners)
    wanted_models = _fold_values(values.models)
    excluded_models = _fold_values(values.excluded_models)
    wanted_has = _fold_values(values.has)
    excluded_has = _fold_values(values.excluded_has)
    wanted_text = _fold_values(values.text)
    excluded_text = _fold_values(values.excluded_text)

    def matches(record: _BeadFilterRecord) -> bool:
        if wanted_types and record.type_labels.isdisjoint(wanted_types):
            return False
        if excluded_types and not record.type_labels.isdisjoint(excluded_types):
            return False
        if wanted_tiers and record.tier_labels.isdisjoint(wanted_tiers):
            return False
        if excluded_tiers and not record.tier_labels.isdisjoint(excluded_tiers):
            return False
        if wanted_statuses and record.status_labels.isdisjoint(wanted_statuses):
            return False
        if excluded_statuses and not record.status_labels.isdisjoint(excluded_statuses):
            return False
        if wanted_sizes and record.size_labels.isdisjoint(wanted_sizes):
            return False
        if excluded_sizes and not record.size_labels.isdisjoint(excluded_sizes):
            return False
        if wanted_projects and record.project_labels.isdisjoint(wanted_projects):
            return False
        if excluded_projects and not record.project_labels.isdisjoint(
            excluded_projects
        ):
            return False
        if wanted_has and record.has_labels.isdisjoint(wanted_has):
            return False
        if excluded_has and not record.has_labels.isdisjoint(excluded_has):
            return False
        if wanted_assignees and not _contains_any(record.assignee, wanted_assignees):
            return False
        if excluded_assignees and _contains_any(record.assignee, excluded_assignees):
            return False
        if wanted_owners and not _contains_any(record.owner, wanted_owners):
            return False
        if excluded_owners and _contains_any(record.owner, excluded_owners):
            return False
        if wanted_models and not _contains_any(record.model, wanted_models):
            return False
        if excluded_models and _contains_any(record.model, excluded_models):
            return False
        if values.since is not None and (
            record.timestamp is None or record.timestamp < values.since
        ):
            return False
        if values.until is not None and (
            record.timestamp is None or record.timestamp > values.until
        ):
            return False
        if record.timestamp is not None and any(
            record.timestamp >= bound for bound in values.excluded_since
        ):
            return False
        if record.timestamp is not None and any(
            record.timestamp <= bound for bound in values.excluded_until
        ):
            return False
        return all(
            any(term in value for value in record.haystack) for term in wanted_text
        ) and not any(
            any(term in value for value in record.haystack) for term in excluded_text
        )

    return matches


def _record(
    snapshot: BeadsSnapshot,
    row_kind: BeadRowKind,
    item: ProjectBead,
) -> _BeadFilterRecord:
    issue = item.issue
    project = item.project
    issue_key = (project, issue.id)
    display_name = snapshot.display_names.get(project, project)
    type_labels = _fold_labels((issue.issue_type.value,))
    tier_labels = _fold_labels(() if issue.tier is None else (issue.tier.value,))
    status_labels = set(_fold_labels((issue.status.value,)))
    if issue_key in snapshot.blocked_ids:
        status_labels.add("blocked")
    if issue.is_ready_to_work:
        status_labels.add("launched")
    if issue_key in snapshot.triage_gates:
        status_labels.add("triage")
    size_labels = _fold_labels(() if issue.size is None else (issue.size.value,))
    has_labels = set[str]()
    if snapshot.plan_links.get(issue_key):
        has_labels.add("plan")
    if issue.changespec_bug_id:
        has_labels.add("bug")
    if issue.dependencies:
        has_labels.add("deps")
    if issue.notes.strip():
        has_labels.add("notes")
    if issue_key in snapshot.triage_gates:
        has_labels.add("triage")
    if issue.plus_one_count:
        has_labels.add("+1")
    if issue.close_history:
        has_labels.add("reopened")
    project_labels = _fold_labels((project, display_name))
    folded_has = frozenset(has_labels)
    folded_statuses = frozenset(status_labels)
    haystack = _fold_haystack(
        (
            issue.id,
            issue.title,
            issue.description,
            issue.notes,
            issue.design,
            *issue.refs,
            plus_one_evidence_search_text(issue.plus_one_evidence),
            close_history_search_text(issue.close_history),
            issue.assignee,
            issue.owner,
            issue.created_by,
            issue.model,
            issue.changespec_name,
            issue.changespec_bug_id,
            issue.parent_id or "",
            project,
            display_name,
            *type_labels,
            *tier_labels,
            *folded_statuses,
            *size_labels,
            *folded_has,
        )
    )
    return _BeadFilterRecord(
        row_kind=row_kind,
        project=project,
        project_display_name=display_name,
        project_labels=project_labels,
        type_labels=type_labels,
        tier_labels=tier_labels,
        status_labels=folded_statuses,
        size_labels=size_labels,
        has_labels=folded_has,
        assignee=issue.assignee,
        owner=issue.owner,
        model=issue.model,
        timestamp=_timestamp_epoch(issue.updated_at or issue.created_at),
        haystack=haystack,
        option_id=row_option_id(snapshot, row_kind, project, issue.id),
        bead_id=issue.id,
    )


def _fold_values(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(value.casefold() for value in values if value)


def _fold_labels(values: tuple[str, ...]) -> frozenset[str]:
    return _fold_values(values)


def _fold_haystack(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.casefold() for value in values if value))


def _contains_any(value: str, needles: frozenset[str]) -> bool:
    folded = value.casefold()
    return bool(folded) and any(needle in folded for needle in needles)


def _timestamp_epoch(value: str) -> int | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from sase.core.time import get_timezone

        parsed = parsed.replace(tzinfo=get_timezone())
    return int(parsed.timestamp())


__all__ = [
    "BeadFilterIndex",
    "build_bead_filter_index",
    "compile_bead_matcher",
]
