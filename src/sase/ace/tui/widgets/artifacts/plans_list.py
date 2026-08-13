"""Selectable document-row models for the Artifacts Plans pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from textual.widgets.option_list import Option

from sase.plan_search.model import PlanSearchMatch

from .bead_plan_links import BeadPlanLink, plan_owner
from .entry_navigation import ArtifactEntryTarget, prepend_jump_hint, prepend_mark_glyph
from .plans_data import ActivePlanDocument, PlanProposal, PlansSnapshot, ProjectArchive
from .plans_rendering import (
    active_plan_text,
    archive_text,
    project_badge,
    proposal_text,
    single_line_text,
)
from .types import ARTIFACTS_ACCENTS

PlanRowKind = Literal["proposal", "active", "archive"]


@dataclass(frozen=True)
class PlanRow:
    """Identity-preserving row backing one selectable plan document."""

    kind: PlanRowKind
    row_id: str
    project: str
    ref_kind: str = "plan"
    proposal: PlanProposal | None = None
    active: ActivePlanDocument | None = None
    archive: PlanSearchMatch | None = None
    archive_role: str | None = None
    bead_link: BeadPlanLink | None = None


def plan_row_target(row: PlanRow) -> ArtifactEntryTarget:
    if row.proposal is not None:
        identity = row.proposal.notification.id
    elif row.active is not None:
        identity = row.active.document.path
    elif row.archive is not None:
        identity = row.archive.plan.path
    else:  # pragma: no cover - construction keeps one payload populated.
        identity = row.row_id
    return (row.ref_kind, row.project, row.kind, identity)


def build_plan_options(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
    matched_option_ids: frozenset[str] | None = None,
    archive_entries: tuple[ProjectArchive, ...] | None = None,
    archive_total: int | None = None,
) -> tuple[list[Option], dict[str, PlanRow]]:
    """Build Proposals, Active plans, and Archive without duplicate paths."""
    options: list[Option] = []
    rows: dict[str, PlanRow] = {}
    active_marks = marks or set()
    if snapshot is None or snapshot.project != project_scope:
        provider_label = snapshot.provider_label if snapshot is not None else "Plan"
        label = (
            f"Loading {provider_label.casefold()} documents…"
            if loading
            else f"{provider_label} documents have not loaded yet."
        )
        return [Option(single_line_text(label), disabled=True)], rows

    filter_active = matched_option_ids is not None
    proposals = tuple(
        (
            proposal,
            row_option_id(
                snapshot, "proposal", proposal.project, proposal.notification.id
            ),
        )
        for proposal in snapshot.proposals
    )
    visible_proposals = tuple(
        item
        for item in proposals
        if matched_option_ids is None or item[1] in matched_option_ids
    )
    options.append(
        _section_option(
            "Proposals",
            len(snapshot.proposals),
            matched_count=len(visible_proposals) if filter_active else None,
        )
    )
    for proposal, option_id in visible_proposals:
        row = PlanRow(
            "proposal",
            option_id,
            proposal.project,
            snapshot.provider_kind,
            proposal=proposal,
        )
        _append_row(
            options,
            rows,
            row,
            proposal_text(
                proposal,
                project_badge=project_badge(snapshot, proposal.project),
            ),
            jump_hints=jump_hints,
            marks=active_marks,
        )
    if not visible_proposals:
        options.append(_empty_option("proposals", filter_active, pending=True))

    active_rows = tuple(
        (
            active,
            row_option_id(snapshot, "active", active.project, active.document.path),
        )
        for active in snapshot.active
    )
    visible_active = tuple(
        item
        for item in active_rows
        if matched_option_ids is None or item[1] in matched_option_ids
    )
    options.append(
        _section_option(
            "Active plans",
            len(snapshot.active),
            matched_count=len(visible_active) if filter_active else None,
        )
    )
    for active, option_id in visible_active:
        row = PlanRow(
            "active",
            option_id,
            active.project,
            snapshot.provider_kind,
            active=active,
            bead_link=active.owner,
        )
        _append_row(
            options,
            rows,
            row,
            active_plan_text(
                active,
                project_badge=project_badge(snapshot, active.project),
            ),
            jump_hints=jump_hints,
            marks=active_marks,
        )
    if not visible_active:
        options.append(_empty_option("active plans", filter_active))

    displayed_archive = snapshot.archive if archive_entries is None else archive_entries
    archive_rows = tuple(
        (
            item,
            row_option_id(snapshot, "archive", item.project, item.match.plan.path),
        )
        for item in displayed_archive
    )
    visible_archive = tuple(
        item
        for item in archive_rows
        if matched_option_ids is None or item[1] in matched_option_ids
    )
    options.append(
        _section_option(
            "Archive",
            len(snapshot.archive) if archive_total is None else archive_total,
            matched_count=len(visible_archive) if filter_active else None,
        )
    )
    for project_archive, option_id in visible_archive:
        owner = plan_owner(
            snapshot.bead_plan_links,
            project=project_archive.project,
            path=project_archive.match.plan.path,
        )
        row = PlanRow(
            "archive",
            option_id,
            project_archive.project,
            snapshot.provider_kind,
            archive=project_archive.match,
            archive_role=project_archive.role,
            bead_link=owner,
        )
        _append_row(
            options,
            rows,
            row,
            archive_text(
                project_archive.match,
                project_badge=project_badge(snapshot, project_archive.project),
            ),
            jump_hints=jump_hints,
            marks=active_marks,
        )
    if not visible_archive:
        options.append(_empty_option("committed plans", filter_active))
    return options, rows


def _append_row(
    options: list[Option],
    rows: dict[str, PlanRow],
    row: PlanRow,
    text: object,
    *,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None,
    marks: set[ArtifactEntryTarget],
) -> None:
    target = plan_row_target(row)
    rows[row.row_id] = row
    options.append(
        Option(
            prepend_jump_hint(
                prepend_mark_glyph(text, target in marks),  # type: ignore[arg-type]
                (jump_hints or {}).get(target),
            ),
            id=row.row_id,
        )
    )


def row_option_id(
    snapshot: PlansSnapshot,
    kind: PlanRowKind,
    project: str,
    identity: str,
) -> str:
    if snapshot.project is None:
        return f"{kind}:{project}:{identity}"
    return f"{kind}:{identity}"


def _section_option(
    label: str,
    count: int,
    *,
    matched_count: int | None = None,
) -> Option:
    text = single_line_text()
    text.append(f"── {label} ", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    count_label = str(count) if matched_count is None else f"{matched_count}/{count}"
    text.append(f"({count_label}) ", style="dim")
    text.append("─" * 8, style="dim #5F5F87")
    return Option(
        text, id=f"header:{label.casefold().replace(' ', '-')}", disabled=True
    )


def _empty_option(label: str, filtered: bool, *, pending: bool = False) -> Option:
    if filtered:
        message = f"  No matching {label}"
    elif pending:
        message = "  No pending proposals"
    else:
        message = f"  No {label}"
    return Option(single_line_text(message, style="dim"), disabled=True)


__all__ = [
    "PlanRow",
    "PlanRowKind",
    "build_plan_options",
    "plan_row_target",
    "row_option_id",
]
