"""In-memory filtering index for document rows in Artifacts Plans."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from .bead_plan_links import plan_owner
from .plans_data import ActivePlanDocument, PlanProposal, PlansSnapshot, ProjectArchive

_PlanFilterRecordKind = Literal["proposal", "active", "archive"]


@dataclass(frozen=True)
class _PlanFilterRecord:
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
    source_key: tuple[object, ...]
    records: tuple[_PlanFilterRecord, ...]
    by_option_id: Mapping[str, _PlanFilterRecord]

    def __iter__(self) -> Iterator[_PlanFilterRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)


def build_plan_filter_index(snapshot: PlansSnapshot) -> PlanFilterIndex:
    records = [
        *(_proposal_record(snapshot, item) for item in snapshot.proposals),
        *(_active_record(snapshot, item) for item in snapshot.active),
        *(_archive_record(snapshot, item) for item in snapshot.archive),
    ]
    frozen_records = tuple(records)
    return PlanFilterIndex(
        source_key=snapshot.source_key,
        records=frozen_records,
        by_option_id=MappingProxyType(
            {record.option_id: record for record in frozen_records}
        ),
    )


def _proposal_record(
    snapshot: PlansSnapshot, proposal: PlanProposal
) -> _PlanFilterRecord:
    return _record(
        snapshot,
        kind="proposal",
        kind_labels=frozenset(("proposal",)),
        project=proposal.project,
        status_labels=frozenset(("proposed",)),
        tier_labels=_fold_labels((proposal.tier, proposal.frontmatter.get("tier", ""))),
        timestamp=_timestamp_epoch(proposal.timestamp),
        haystack=(
            proposal.title,
            proposal.notification.id,
            proposal.plan_path,
            proposal.frontmatter.get("goal", ""),
            proposal.body,
            proposal.agent,
            proposal.provider_model,
            *proposal.frontmatter.values(),
        ),
        identity=proposal.notification.id,
    )


def _active_record(
    snapshot: PlansSnapshot,
    active: ActivePlanDocument,
) -> _PlanFilterRecord:
    document = active.document
    frontmatter = document.frontmatter
    return _record(
        snapshot,
        kind="active",
        kind_labels=frozenset(("active", active.role)),
        project=active.project,
        status_labels=_fold_labels((frontmatter.get("status", ""),)),
        tier_labels=_fold_labels((frontmatter.get("tier", ""),)),
        timestamp=_timestamp_epoch(
            frontmatter.get("create_time", "") or frontmatter.get("created_at", "")
        ),
        haystack=(
            frontmatter.get("title", ""),
            document.path,
            document.reference,
            active.owner.bead_id,
            frontmatter.get("goal", ""),
            document.body,
            *frontmatter.values(),
        ),
        identity=document.path,
    )


def _archive_record(
    snapshot: PlansSnapshot,
    project_archive: ProjectArchive,
) -> _PlanFilterRecord:
    project = project_archive.project
    plan = project_archive.match.plan
    owner = plan_owner(
        snapshot.bead_plan_links,
        project=project,
        path=plan.path,
    )
    return _record(
        snapshot,
        kind="archive",
        kind_labels=_fold_labels(("archive", project_archive.role)),
        project=project,
        status_labels=_fold_labels((plan.status, plan.frontmatter.get("status", ""))),
        tier_labels=_fold_labels((plan.kind, plan.frontmatter.get("tier", ""))),
        timestamp=_timestamp_epoch(plan.created_at),
        haystack=(
            plan.title,
            plan.name,
            plan.relpath,
            plan.path,
            plan.summary,
            "" if owner is None else owner.bead_id,
            "" if owner is None else owner.reference,
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
    return _PlanFilterRecord(
        kind=kind,
        kind_labels=kind_labels,
        project=project,
        project_display_name=display_name,
        project_labels=project_labels,
        status_labels=status_labels,
        tier_labels=tier_labels,
        timestamp=timestamp,
        haystack=_fold_haystack(
            (
                *haystack,
                project,
                display_name,
                *status_labels,
                *tier_labels,
                *kind_labels,
            )
        ),
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
    "build_plan_filter_index",
]
