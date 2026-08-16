"""Selectable document-row models for the Artifacts Plans pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from textual.widgets.option_list import Option

from sase.plan_search.model import PlanSearchMatch

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import ArtifactGroupBuildResult, build_grouped_rows
from ...models.group_fold import GroupFoldRegistry
from .bead_plan_links import BeadPlanLink, plan_owner
from .entry_navigation import ArtifactEntryTarget, prepend_jump_hint, prepend_mark_glyph
from .group_banner import format_group_banner_option
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

_KIND_LABELS: dict[str, str] = {
    "proposal": "Proposals",
    "active": "Active plans",
    "archive": "Archive",
}


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
    return ArtifactEntryTarget(
        pane_id=f"ref:{row.ref_kind}",
        parts=(row.project, row.kind, identity),
    )


def _plan_tier_value(row: PlanRow) -> str:
    if row.proposal is not None:
        return row.proposal.tier or row.proposal.frontmatter.get("tier", "")
    if row.active is not None:
        return row.active.document.frontmatter.get("tier", "")
    if row.archive is not None:
        plan = row.archive.plan
        return plan.kind or plan.frontmatter.get("tier", "")
    return ""


def _plan_status_value(row: PlanRow) -> str:
    if row.proposal is not None:
        return "proposed"
    if row.active is not None:
        return row.active.document.frontmatter.get("status", "") or "active"
    if row.archive is not None:
        plan = row.archive.plan
        return plan.status or plan.frontmatter.get("status", "") or "archived"
    return ""


def _plan_row_key_values(row: PlanRow, mode_id: str) -> tuple[str, ...]:
    if mode_id == "by_kind":
        return (row.kind, _plan_tier_value(row))
    if mode_id == "by_status":
        return (_plan_status_value(row),)
    if mode_id == "by_project":
        return (row.project,)
    return ("",)


def _plan_group_label(
    mode_id: str,
    level: int,
    value: str,
    *,
    display_names: Mapping[str, str],
) -> str:
    if mode_id == "by_kind" and level == 0:
        return _KIND_LABELS.get(value, value.title() if value else "Unknown")
    if mode_id == "by_kind":
        return value.title() if value else "(no tier)"
    if mode_id == "by_project":
        return (display_names.get(value, value) if value else None) or "(no project)"
    if mode_id == "by_status":
        return value.title() if value else "(no status)"
    return value or "Unknown"


def build_grouped_plan_rows(
    ordered_rows: list[PlanRow],
    *,
    mode: PaneGroupingModeDecl,
    snapshot: PlansSnapshot,
    fold_registry: GroupFoldRegistry | None,
) -> ArtifactGroupBuildResult[PlanRow]:
    """Bucket already-filtered Plans rows by the active declared mode."""
    return build_grouped_rows(
        ordered_rows,
        pane_id=f"ref:{snapshot.provider_kind}",
        mode_id=mode.id,
        keys=mode.keys,
        key_values=lambda row: _plan_row_key_values(row, mode.id),
        label_for=lambda level, value: _plan_group_label(
            mode.id, level, value, display_names=snapshot.display_names
        ),
        target_for=plan_row_target,
        fold_registry=fold_registry,
    )


def build_plan_options(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    mode: PaneGroupingModeDecl | None = None,
    fold_registry: GroupFoldRegistry | None = None,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
    matched_option_ids: frozenset[str] | None = None,
    archive_entries: tuple[ProjectArchive, ...] | None = None,
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> tuple[list[Option], dict[str, PlanRow], tuple[tuple[str, ...], ...]]:
    """Build Proposals, Active plans, and Archive without duplicate paths.

    Returns ``(options, rows, known_group_keys)``.
    """
    rows: dict[str, PlanRow] = {}
    active_marks = marks or set()
    if snapshot is None or snapshot.project != project_scope:
        provider_label = snapshot.provider_label if snapshot is not None else "Plan"
        label = (
            f"Loading {provider_label.casefold()} documents…"
            if loading
            else f"{provider_label} documents have not loaded yet."
        )
        return [Option(single_line_text(label), disabled=True)], rows, ()

    filter_active = matched_option_ids is not None
    ordered_rows: list[PlanRow] = []
    row_texts: dict[str, object] = {}

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
    for proposal, option_id in visible_proposals:
        row = PlanRow(
            "proposal",
            option_id,
            proposal.project,
            snapshot.provider_kind,
            proposal=proposal,
        )
        rows[row.row_id] = row
        ordered_rows.append(row)
        row_texts[row.row_id] = proposal_text(
            proposal,
            project_badge=project_badge(snapshot, proposal.project),
            accent=accent,
        )

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
    for active, option_id in visible_active:
        row = PlanRow(
            "active",
            option_id,
            active.project,
            snapshot.provider_kind,
            active=active,
            bead_link=active.owner,
        )
        rows[row.row_id] = row
        ordered_rows.append(row)
        row_texts[row.row_id] = active_plan_text(
            active,
            project_badge=project_badge(snapshot, active.project),
            accent=accent,
        )

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
        rows[row.row_id] = row
        ordered_rows.append(row)
        row_texts[row.row_id] = archive_text(
            project_archive.match,
            project_badge=project_badge(snapshot, project_archive.project),
            accent=accent,
        )

    options: list[Option] = []
    known_group_keys: tuple[tuple[str, ...], ...] = ()
    if mode is None:
        for row in ordered_rows:
            _append_row(
                options,
                row,
                row_texts[row.row_id],
                jump_hints=jump_hints,
                marks=active_marks,
            )
    else:
        grouped = build_grouped_plan_rows(
            ordered_rows,
            mode=mode,
            snapshot=snapshot,
            fold_registry=fold_registry,
        )
        known_group_keys = grouped.known_group_keys
        hints = jump_hints or {}
        for grouped_row in grouped.rows:
            if grouped_row.kind == "banner" and grouped_row.banner is not None:
                options.append(
                    format_group_banner_option(
                        grouped_row.banner,
                        accent=accent,
                        hint_char=hints.get(grouped_row.banner.target),
                    )
                )
                continue
            grouped_plan_row = grouped_row.item
            assert grouped_plan_row is not None
            _append_row(
                options,
                grouped_plan_row,
                row_texts[grouped_plan_row.row_id],
                jump_hints=jump_hints,
                marks=active_marks,
            )

    if not visible_proposals:
        options.append(_empty_option("proposals", filter_active, pending=True))
    if not visible_active:
        options.append(_empty_option("active plans", filter_active))
    if not visible_archive:
        options.append(_empty_option("committed plans", filter_active))
    return options, rows, known_group_keys


def _append_row(
    options: list[Option],
    row: PlanRow,
    text: object,
    *,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None,
    marks: set[ArtifactEntryTarget],
) -> None:
    target = plan_row_target(row)
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
