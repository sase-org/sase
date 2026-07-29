"""In-memory filtering index for Artifacts plan rows."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from sase.bead.model import Issue
from sase.plan_search.filter_query import PlanFilterValues

from .plans_data import PlanProposal, PlansSnapshot, ProjectArchive

_PlanFilterRecordKind = Literal["proposal", "epic", "phase", "archive"]


@dataclass(frozen=True)
class _PlanFilterRecord:
    """One prefolded, presentation-neutral plan row."""

    kind: _PlanFilterRecordKind
    project: str
    project_display_name: str
    project_labels: frozenset[str]
    status_labels: frozenset[str]
    tier_labels: frozenset[str]
    timestamp: int | None
    haystack: tuple[str, ...]
    identity: str
    option_id: str
    kind_labels: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PlanFilterIndex:
    """Immutable record snapshot used by live plans filtering."""

    source_key: tuple[object, ...]
    records: tuple[_PlanFilterRecord, ...]
    by_option_id: Mapping[str, _PlanFilterRecord]

    def __iter__(self) -> Iterator[_PlanFilterRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)


def build_plan_filter_index(snapshot: PlansSnapshot) -> PlanFilterIndex:
    """Build prefolded records for every row in *snapshot*."""
    records: list[_PlanFilterRecord] = []

    for proposal in snapshot.proposals:
        records.append(_proposal_record(snapshot, proposal))

    for project_epic in snapshot.epics:
        project = project_epic.project
        epic = project_epic.issue
        records.append(_issue_record(snapshot, project, epic, kind="epic"))
        for project_phase in snapshot.phases_by_epic.get((project, epic.id), ()):
            records.append(
                _issue_record(
                    snapshot,
                    project,
                    project_phase.issue,
                    kind="phase",
                )
            )

    for project_archive in snapshot.archive:
        records.append(_archive_record(snapshot, project_archive))

    frozen_records = tuple(records)
    return PlanFilterIndex(
        source_key=snapshot.source_key,
        records=frozen_records,
        by_option_id=MappingProxyType(
            {record.option_id: record for record in frozen_records}
        ),
    )


def build_plan_archive_filter_records(
    snapshot: PlansSnapshot,
    archive: tuple[ProjectArchive, ...],
) -> tuple[_PlanFilterRecord, ...]:
    """Build prefolded records for a worker-fetched archive corpus."""
    return tuple(_archive_record(snapshot, item) for item in archive)


def compile_plan_matcher(
    values: PlanFilterValues,
) -> Callable[[_PlanFilterRecord], bool]:
    """Compile *values* into a cheap, reusable record predicate."""
    wanted_kinds = frozenset(value.casefold() for value in values.kinds)
    excluded_kinds = frozenset(value.casefold() for value in values.excluded_kinds)
    wanted_statuses = frozenset(value.casefold() for value in values.statuses)
    excluded_statuses = frozenset(
        value.casefold() for value in values.excluded_statuses
    )
    wanted_tiers = frozenset(value.casefold() for value in values.tiers)
    excluded_tiers = frozenset(value.casefold() for value in values.excluded_tiers)
    wanted_projects = frozenset(value.casefold() for value in values.projects)
    excluded_projects = frozenset(
        value.casefold() for value in values.excluded_projects
    )
    wanted_text = tuple(value.casefold() for value in values.text)
    excluded_text = tuple(value.casefold() for value in values.excluded_text)
    since = values.since
    until = values.until

    def matches(record: _PlanFilterRecord) -> bool:
        kind_labels = record.kind_labels or frozenset((record.kind,))
        if wanted_kinds and kind_labels.isdisjoint(wanted_kinds):
            return False
        if excluded_kinds and not kind_labels.isdisjoint(excluded_kinds):
            return False
        if wanted_statuses and record.status_labels.isdisjoint(wanted_statuses):
            return False
        if excluded_statuses and not record.status_labels.isdisjoint(excluded_statuses):
            return False
        if wanted_tiers and record.tier_labels.isdisjoint(wanted_tiers):
            return False
        if excluded_tiers and not record.tier_labels.isdisjoint(excluded_tiers):
            return False
        if wanted_projects and record.project_labels.isdisjoint(wanted_projects):
            return False
        if excluded_projects and not record.project_labels.isdisjoint(
            excluded_projects
        ):
            return False
        if since is not None:
            if record.timestamp is None or record.timestamp < since:
                return False
        if until is not None:
            if record.timestamp is None or record.timestamp > until:
                return False
        return all(
            any(term in value for value in record.haystack) for term in wanted_text
        ) and not any(
            any(term in value for value in record.haystack) for term in excluded_text
        )

    return matches


def _proposal_record(
    snapshot: PlansSnapshot,
    proposal: PlanProposal,
) -> _PlanFilterRecord:
    tiers = _fold_labels((proposal.tier, proposal.frontmatter.get("tier", "")))
    identity = proposal.notification.id
    return _record(
        snapshot,
        kind="proposal",
        kind_labels=frozenset(("proposal",)),
        project=proposal.project,
        status_labels=frozenset(("proposed",)),
        tier_labels=tiers,
        timestamp=_timestamp_epoch(proposal.timestamp),
        haystack=(
            proposal.title,
            identity,
            proposal.plan_path,
            proposal.frontmatter.get("goal", ""),
            proposal.body,
            proposal.agent,
            proposal.provider_model,
            *proposal.frontmatter.values(),
        ),
        identity=identity,
    )


def _resolved_plan_path(
    snapshot: PlansSnapshot,
    project: str,
    issue: Issue,
) -> str:
    document = snapshot.linked_plan_documents.get((project, issue.id))
    if document is None or not document.available:
        return ""
    return document.path


def _issue_record(
    snapshot: PlansSnapshot,
    project: str,
    issue: Issue,
    *,
    kind: Literal["epic", "phase"],
) -> _PlanFilterRecord:
    status_labels = {issue.status.value.casefold()}
    issue_key = (project, issue.id)
    if issue_key in snapshot.blocked_ids:
        status_labels.add("blocked")
    elif issue_key in snapshot.ready_ids:
        status_labels.add("ready")
    elif issue.is_ready_to_work:
        status_labels.add("launched")
    tier_labels = (
        frozenset() if issue.tier is None else frozenset((issue.tier.value.casefold(),))
    )
    return _record(
        snapshot,
        kind=kind,
        kind_labels=frozenset((kind,)),
        project=project,
        status_labels=frozenset(status_labels),
        tier_labels=tier_labels,
        timestamp=_timestamp_epoch(issue.created_at),
        haystack=(
            issue.title,
            issue.id,
            issue.description,
            issue.notes,
            # Match the stable reference and the path it resolves to, so a
            # query works whichever form the user has in front of them.
            issue.design,
            _resolved_plan_path(snapshot, project, issue),
            issue.assignee,
            issue.owner,
            issue.model,
            issue.changespec_name,
            issue.changespec_bug_id,
        ),
        identity=issue.id,
    )


def _archive_record(
    snapshot: PlansSnapshot,
    project_archive: ProjectArchive,
) -> _PlanFilterRecord:
    project = project_archive.project
    plan = project_archive.match.plan
    status_labels = _fold_labels((plan.status, plan.frontmatter.get("status", "")))
    tier_labels = _fold_labels((plan.kind, plan.frontmatter.get("tier", "")))
    return _record(
        snapshot,
        kind="archive",
        kind_labels=_fold_labels(("archive", project_archive.role)),
        project=project,
        status_labels=status_labels,
        tier_labels=tier_labels,
        timestamp=_timestamp_epoch(plan.created_at),
        haystack=(
            plan.title,
            plan.name,
            plan.relpath,
            plan.path,
            plan.summary,
            plan.frontmatter.get("goal", ""),
            plan.body,
            *plan.frontmatter.values(),
        ),
        identity=plan.path,
    )


def _record(
    snapshot: PlansSnapshot,
    *,
    kind: _PlanFilterRecordKind,
    kind_labels: frozenset[str],
    project: str,
    status_labels: frozenset[str],
    tier_labels: frozenset[str],
    timestamp: int | None,
    haystack: tuple[str, ...],
    identity: str,
) -> _PlanFilterRecord:
    display_name = snapshot.display_names.get(project, project)
    project_labels = _fold_labels((project, display_name))
    folded_haystack = _fold_haystack(
        (
            *haystack,
            project,
            display_name,
            *status_labels,
            *tier_labels,
            *kind_labels,
        )
    )
    return _PlanFilterRecord(
        kind=kind,
        kind_labels=kind_labels,
        project=project,
        project_display_name=display_name,
        project_labels=project_labels,
        status_labels=status_labels,
        tier_labels=tier_labels,
        timestamp=timestamp,
        haystack=folded_haystack,
        identity=identity,
        option_id=_row_option_id(snapshot, kind, project, identity),
    )


def _row_option_id(
    snapshot: PlansSnapshot,
    kind: _PlanFilterRecordKind,
    project: str,
    identity: str,
) -> str:
    if snapshot.project is None:
        return f"{kind}:{project}:{identity}"
    return f"{kind}:{identity}"


def _fold_labels(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(value.casefold() for value in values if value)


def _fold_haystack(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.casefold() for value in values if value))


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
    "PlanFilterIndex",
    "build_plan_archive_filter_records",
    "build_plan_filter_index",
    "compile_plan_matcher",
]
