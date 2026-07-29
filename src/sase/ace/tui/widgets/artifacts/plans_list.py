"""Selectable row models and option construction for the Artifacts Plans pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from textual.widgets.option_list import Option

from sase.bead.model import Issue
from sase.plan_search.model import PlanSearchMatch

from .plans_data import PlanProposal, PlansSnapshot, ProjectArchive, ProjectIssue
from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
)
from .plans_rendering import (
    BLOCKED_STATE_GLYPH,
    LAUNCHED_STATE_GLYPH,
    READY_STATE_GLYPH,
    archive_text,
    epic_text,
    phase_text,
    project_badge,
    proposal_text,
    single_line_text,
)
from .types import ARTIFACTS_ACCENTS


PlanRowKind = Literal["proposal", "epic", "phase", "archive"]


@dataclass(frozen=True)
class PlanRow:
    """Identity-preserving row backing one selectable OptionList entry."""

    kind: PlanRowKind
    row_id: str
    project: str
    proposal: PlanProposal | None = None
    issue: Issue | None = None
    archive: PlanSearchMatch | None = None


def _plan_entry_target(
    kind: PlanRowKind,
    project: str,
    identity: str,
) -> ArtifactEntryTarget:
    """Return a project-aware identity that survives scope presentation changes."""
    return ("plan", project, kind, identity)


def plan_row_target(row: PlanRow) -> ArtifactEntryTarget:
    if row.proposal is not None:
        identity = row.proposal.notification.id
    elif row.issue is not None:
        identity = row.issue.id
    elif row.archive is not None:
        identity = row.archive.plan.path
    else:  # pragma: no cover - PlanRow construction keeps one payload populated.
        identity = row.row_id
    return _plan_entry_target(row.kind, row.project, identity)


def build_plan_options(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    expanded_epics: set[tuple[str, str]],
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
    matched_option_ids: frozenset[str] | None = None,
    archive_entries: tuple[ProjectArchive, ...] | None = None,
    archive_total: int | None = None,
) -> tuple[list[Option], dict[str, PlanRow]]:
    """Build the grouped plan options and their identity-preserving row map."""
    options: list[Option] = []
    rows: dict[str, PlanRow] = {}
    active_marks = marks or set()
    if snapshot is None or snapshot.project != project_scope:
        label = "Loading plans…" if loading else "Plans have not loaded yet."
        options.append(Option(single_line_text(label), disabled=True))
        return options, rows

    filter_active = matched_option_ids is not None
    proposal_entries = tuple(
        (
            proposal,
            row_option_id(
                snapshot,
                "proposal",
                proposal.project,
                proposal.notification.id,
            ),
        )
        for proposal in snapshot.proposals
    )
    visible_proposals = tuple(
        entry
        for entry in proposal_entries
        if matched_option_ids is None or entry[1] in matched_option_ids
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
            proposal=proposal,
        )
        rows[option_id] = row
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        proposal_text(
                            proposal,
                            project_badge=project_badge(snapshot, proposal.project),
                        ),
                        plan_row_target(row) in active_marks,
                    ),
                    (jump_hints or {}).get(plan_row_target(row)),
                ),
                id=option_id,
            )
        )
    if not visible_proposals:
        options.append(
            Option(
                single_line_text(
                    "  No matching proposals"
                    if filter_active
                    else "  No pending proposals",
                    style="dim",
                ),
                disabled=True,
            )
        )

    epic_entries: tuple[ProjectIssue, ...] = snapshot.epics
    visible_epics = 0
    epic_options: list[Option] = []
    epic_rows: dict[str, PlanRow] = {}
    for project_epic in epic_entries:
        project = project_epic.project
        epic = project_epic.issue
        epic_key = (project, epic.id)
        option_id = row_option_id(snapshot, "epic", project, epic.id)
        phases = snapshot.phases_by_epic.get(epic_key, ())
        epic_matches = matched_option_ids is None or option_id in matched_option_ids
        matching_phase_ids = frozenset(
            phase_option_id
            for project_phase in phases
            if (
                phase_option_id := row_option_id(
                    snapshot,
                    "phase",
                    project,
                    project_phase.issue.id,
                )
            )
            in (matched_option_ids or ())
        )
        if filter_active and not epic_matches and not matching_phase_ids:
            continue

        visible_epics += 1
        row = PlanRow("epic", option_id, project, issue=epic)
        epic_rows[option_id] = row
        effectively_expanded = epic_key in expanded_epics or bool(matching_phase_ids)
        epic_options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        epic_text(
                            epic,
                            tuple(item.issue for item in phases),
                            expanded=effectively_expanded,
                            project=project,
                            ready_ids=snapshot.ready_ids,
                            blocked_ids=snapshot.blocked_ids,
                            project_badge=project_badge(snapshot, project),
                        ),
                        plan_row_target(row) in active_marks,
                    ),
                    (jump_hints or {}).get(plan_row_target(row)),
                ),
                id=option_id,
            )
        )
        if not effectively_expanded:
            continue
        for project_phase in phases:
            phase = project_phase.issue
            phase_option_id = row_option_id(snapshot, "phase", project, phase.id)
            if (
                filter_active
                and phase_option_id not in matching_phase_ids
                and not (epic_matches and epic_key in expanded_epics)
            ):
                continue
            row = PlanRow(
                "phase",
                phase_option_id,
                project,
                issue=phase,
            )
            epic_rows[phase_option_id] = row
            epic_options.append(
                Option(
                    prepend_jump_hint(
                        prepend_mark_glyph(
                            phase_text(
                                phase,
                                project=project,
                                ready_ids=snapshot.ready_ids,
                                blocked_ids=snapshot.blocked_ids,
                            ),
                            plan_row_target(row) in active_marks,
                        ),
                        (jump_hints or {}).get(plan_row_target(row)),
                    ),
                    id=phase_option_id,
                )
            )
    options.append(
        _section_option(
            "Epics",
            len(snapshot.epics),
            matched_count=visible_epics if filter_active else None,
        )
    )
    options.extend(epic_options)
    rows.update(epic_rows)
    if not visible_epics:
        options.append(
            Option(
                single_line_text(
                    "  No matching epic beads" if filter_active else "  No epic beads",
                    style="dim",
                ),
                disabled=True,
            )
        )

    displayed_archive: tuple[ProjectArchive, ...] = (
        snapshot.archive if archive_entries is None else archive_entries
    )
    archive_rows = tuple(
        (
            project_archive,
            row_option_id(
                snapshot,
                "archive",
                project_archive.project,
                project_archive.match.plan.path,
            ),
        )
        for project_archive in displayed_archive
    )
    visible_archive = tuple(
        entry
        for entry in archive_rows
        if matched_option_ids is None or entry[1] in matched_option_ids
    )
    options.append(
        _section_option(
            "Plan archive",
            len(snapshot.archive) if archive_total is None else archive_total,
            matched_count=len(visible_archive) if filter_active else None,
        )
    )
    for project_archive, option_id in visible_archive:
        project = project_archive.project
        match = project_archive.match
        row = PlanRow(
            "archive",
            option_id,
            project,
            archive=match,
        )
        rows[option_id] = row
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        archive_text(
                            match,
                            project_badge=project_badge(snapshot, project),
                        ),
                        plan_row_target(row) in active_marks,
                    ),
                    (jump_hints or {}).get(plan_row_target(row)),
                ),
                id=option_id,
            )
        )
    if not visible_archive:
        options.append(
            Option(
                single_line_text(
                    "  No matching committed plans"
                    if filter_active
                    else "  No committed plans",
                    style="dim",
                ),
                disabled=True,
            )
        )
    return options, rows


def row_option_id(
    snapshot: PlansSnapshot,
    kind: PlanRowKind,
    project: str,
    identity: str,
) -> str:
    """Return a stable option ID, namespaced when browsing all projects."""
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
    if label == "Epics":
        text.append("· ", style="dim")
        text.append(BLOCKED_STATE_GLYPH, style="bold #FF5F5F")
        text.append(" blocked ", style="dim")
        text.append(READY_STATE_GLYPH, style="bold #5FD787")
        text.append(" ready ", style="dim")
        text.append(LAUNCHED_STATE_GLYPH, style="bold #00D7AF")
        text.append(" launched ", style="dim")
        text.append("──", style="dim #5F5F87")
    else:
        text.append("─" * 8, style="dim #5F5F87")
    return Option(
        text, id=f"header:{label.casefold().replace(' ', '-')}", disabled=True
    )


__all__ = [
    "PlanRow",
    "PlanRowKind",
    "build_plan_options",
    "plan_row_target",
    "row_option_id",
]
