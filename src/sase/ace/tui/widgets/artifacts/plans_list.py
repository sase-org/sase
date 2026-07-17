"""Selectable row models and option construction for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.widgets.option_list import Option

from sase.bead.model import Issue
from sase.plan_search.model import PlanSearchMatch

from .plans_data import PlanProposal, PlansSnapshot, ProjectArchive, ProjectIssue
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


def build_plan_options(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    expanded_epics: set[tuple[str, str]],
) -> tuple[list[Option], dict[str, PlanRow]]:
    """Build the grouped plan options and their identity-preserving row map."""
    options: list[Option] = []
    rows: dict[str, PlanRow] = {}
    if snapshot is None or snapshot.project != project_scope:
        label = "Loading plans…" if loading else "Plans have not loaded yet."
        options.append(Option(single_line_text(label), disabled=True))
        return options, rows

    options.append(_section_option("Proposals", len(snapshot.proposals)))
    for proposal in snapshot.proposals:
        option_id = row_option_id(
            snapshot,
            "proposal",
            proposal.project,
            proposal.notification.id,
        )
        rows[option_id] = PlanRow(
            "proposal",
            option_id,
            proposal.project,
            proposal=proposal,
        )
        options.append(
            Option(
                proposal_text(
                    proposal,
                    project_badge=project_badge(snapshot, proposal.project),
                ),
                id=option_id,
            )
        )
    if not snapshot.proposals:
        options.append(
            Option(
                single_line_text("  No pending proposals", style="dim"),
                disabled=True,
            )
        )

    options.append(_section_option("Epics", len(snapshot.epics)))
    epic_entries: tuple[ProjectIssue, ...] = snapshot.epics
    for project_epic in epic_entries:
        project = project_epic.project
        epic = project_epic.issue
        epic_key = (project, epic.id)
        option_id = row_option_id(snapshot, "epic", project, epic.id)
        rows[option_id] = PlanRow("epic", option_id, project, issue=epic)
        phases = snapshot.phases_by_epic.get(epic_key, ())
        options.append(
            Option(
                epic_text(
                    epic,
                    tuple(item.issue for item in phases),
                    expanded=epic_key in expanded_epics,
                    project=project,
                    ready_ids=snapshot.ready_ids,
                    blocked_ids=snapshot.blocked_ids,
                    project_badge=project_badge(snapshot, project),
                ),
                id=option_id,
            )
        )
        if epic_key not in expanded_epics:
            continue
        for project_phase in phases:
            phase = project_phase.issue
            phase_option_id = row_option_id(snapshot, "phase", project, phase.id)
            rows[phase_option_id] = PlanRow(
                "phase",
                phase_option_id,
                project,
                issue=phase,
            )
            options.append(
                Option(
                    phase_text(
                        phase,
                        project=project,
                        ready_ids=snapshot.ready_ids,
                        blocked_ids=snapshot.blocked_ids,
                    ),
                    id=phase_option_id,
                )
            )
    if not snapshot.epics:
        options.append(
            Option(
                single_line_text("  No epic beads", style="dim"),
                disabled=True,
            )
        )

    options.append(_section_option("Plan archive", len(snapshot.archive)))
    archive_entries: tuple[ProjectArchive, ...] = snapshot.archive
    for project_archive in archive_entries:
        project = project_archive.project
        match = project_archive.match
        plan = match.plan
        option_id = row_option_id(snapshot, "archive", project, plan.path)
        rows[option_id] = PlanRow(
            "archive",
            option_id,
            project,
            archive=match,
        )
        options.append(
            Option(
                archive_text(
                    match,
                    project_badge=project_badge(snapshot, project),
                ),
                id=option_id,
            )
        )
    if not snapshot.archive:
        options.append(
            Option(
                single_line_text("  No committed plans", style="dim"),
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


def _section_option(label: str, count: int) -> Option:
    text = single_line_text()
    text.append(f"── {label} ", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    text.append(f"({count}) ", style="dim")
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


__all__ = ["PlanRow", "PlanRowKind", "build_plan_options", "row_option_id"]
