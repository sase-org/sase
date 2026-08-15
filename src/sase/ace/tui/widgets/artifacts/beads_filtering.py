"""In-memory filtering index for rows in the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from sase.bead.plus_one_presentation import plus_one_evidence_search_text
from sase.bead.reopen_presentation import close_history_search_text
from sase.bug_links import normalize_external_ref

from .beads_data import BeadsSnapshot, ProjectBead
from .beads_data_models import ExternalIssueLink
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
    bug_labels: frozenset[str]
    issue_labels: frozenset[str]
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
    external_links = snapshot.external_links.get(issue_key, ())
    if _issue_has_external_ref(issue, project):
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
    bug_labels = _bug_labels(external_links)
    issue_labels = _issue_labels(external_links)
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
            issue.patch_name,
            issue.patch_bug_id,
            issue.external_ref,
            issue.parent_id or "",
            project,
            display_name,
            *(
                value
                for link in external_links
                for value in (
                    link.external_ref,
                    link.project,
                    link.display_project,
                    link.issue_id,
                    link.state,
                    link.relation,
                    "" if link.issue is None else link.issue.title,
                    "" if link.issue is None else link.issue.body,
                    "" if link.issue is None else link.issue.url,
                    "" if link.issue is None else " ".join(link.issue.labels),
                )
            ),
            *type_labels,
            *tier_labels,
            *folded_statuses,
            *size_labels,
            *folded_has,
            *bug_labels,
            *issue_labels,
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
        bug_labels=bug_labels,
        issue_labels=issue_labels,
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


def _issue_has_external_ref(issue: object, project: str) -> bool:
    external_ref = normalize_external_ref(
        getattr(issue, "external_ref", ""),
        project=project,
    )
    if external_ref:
        return True
    return any(
        ref.strip().casefold().startswith("bug:")
        and bool(normalize_external_ref(ref, project=project))
        for ref in getattr(issue, "refs", ())
    )


def _bug_labels(links: tuple[ExternalIssueLink, ...]) -> frozenset[str]:
    labels: set[str] = set()
    for link in links:
        labels.update(
            {
                link.external_ref,
                link.issue_id,
                f"#{link.issue_id}",
                link.state,
                link.relation,
                link.project,
                link.display_project,
            }
        )
        if link.stale:
            labels.add("stale")
        if link.drift:
            labels.add("drift")
    if not labels:
        labels.add("none")
    return _fold_labels(tuple(labels))


def _issue_labels(links: tuple[ExternalIssueLink, ...]) -> frozenset[str]:
    labels: set[str] = set()
    for link in links:
        if link.issue is None:
            continue
        labels.update(link.issue.labels)
    return _fold_labels(tuple(labels))


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
]
