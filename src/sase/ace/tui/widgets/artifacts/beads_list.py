"""Selectable rows and option construction for the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from textual.widgets.option_list import Option

from sase.bead.model import Issue

from .beads_data import BeadsSnapshot
from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
)
from .beads_rendering import (
    BLOCKED_STATE_GLYPH,
    LAUNCHED_STATE_GLYPH,
    READY_STATE_GLYPH,
    epic_text,
    phase_text,
    project_badge,
    single_line_text,
    task_text,
)
from .types import ARTIFACTS_ACCENTS

BeadRowKind = Literal["task", "epic", "phase"]


@dataclass(frozen=True)
class BeadRow:
    """Stable identity and payload for one selectable bead row."""

    kind: BeadRowKind
    row_id: str
    project: str
    issue: Issue


def bead_row_target(row: BeadRow) -> ArtifactEntryTarget:
    return ("bead", row.project, row.kind, row.issue.id)


def row_option_id(
    snapshot: BeadsSnapshot,
    kind: BeadRowKind,
    project: str,
    bead_id: str,
) -> str:
    if snapshot.project is None:
        return f"{kind}:{project}:{bead_id}"
    return f"{kind}:{bead_id}"


def build_bead_options(
    snapshot: BeadsSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    expanded_epics: set[tuple[str, str]],
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
) -> tuple[list[Option], dict[str, BeadRow]]:
    options: list[Option] = []
    rows: dict[str, BeadRow] = {}
    if snapshot is None or snapshot.project != project_scope:
        label = "Loading beads…" if loading else "Beads have not loaded yet."
        return [Option(single_line_text(label), disabled=True)], rows

    for project, error in sorted(snapshot.errors.items()):
        label = snapshot.display_names.get(project, project)
        options.append(
            Option(
                single_line_text(f"! {label}: {error}", style="bold #FF5F5F"),
                id=f"error:{project}",
                disabled=True,
            )
        )

    active_marks = marks or set()
    triage_count = sum(
        (task.project, task.issue.id) in snapshot.triage_gates
        for task in snapshot.tasks
    )
    options.append(
        _section_option("Tasks", len(snapshot.tasks), triage_count=triage_count)
    )
    for item in snapshot.tasks:
        issue = item.issue
        option_id = row_option_id(snapshot, "task", item.project, issue.id)
        row = BeadRow("task", option_id, item.project, issue)
        rows[option_id] = row
        target = bead_row_target(row)
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        task_text(
                            issue,
                            triage=(item.project, issue.id) in snapshot.triage_gates,
                            plan_link=bool(
                                snapshot.plan_links.get((item.project, issue.id))
                            ),
                            project_badge=project_badge(snapshot, item.project),
                        ),
                        target in active_marks,
                    ),
                    (jump_hints or {}).get(target),
                ),
                id=option_id,
            )
        )
    if not snapshot.tasks:
        options.append(
            Option(single_line_text("  No task beads", style="dim"), disabled=True)
        )

    options.append(_section_option("Epics", len(snapshot.epics)))
    for item in snapshot.epics:
        project = item.project
        epic = item.issue
        epic_key = (project, epic.id)
        option_id = row_option_id(snapshot, "epic", project, epic.id)
        row = BeadRow("epic", option_id, project, epic)
        rows[option_id] = row
        target = bead_row_target(row)
        phases = snapshot.phases_by_epic.get(epic_key, ())
        expanded = epic_key in expanded_epics
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        epic_text(
                            epic,
                            tuple(phase.issue for phase in phases),
                            expanded=expanded,
                            project=project,
                            ready_ids=snapshot.ready_ids,
                            blocked_ids=snapshot.blocked_ids,
                            plan_link=bool(snapshot.plan_links.get(epic_key)),
                            project_badge=project_badge(snapshot, project),
                        ),
                        target in active_marks,
                    ),
                    (jump_hints or {}).get(target),
                ),
                id=option_id,
            )
        )
        if not expanded:
            continue
        for phase_item in phases:
            phase = phase_item.issue
            phase_id = row_option_id(snapshot, "phase", project, phase.id)
            phase_row = BeadRow("phase", phase_id, project, phase)
            rows[phase_id] = phase_row
            phase_target = bead_row_target(phase_row)
            options.append(
                Option(
                    prepend_jump_hint(
                        prepend_mark_glyph(
                            phase_text(
                                phase,
                                plan_link=bool(
                                    snapshot.plan_links.get((project, phase.id))
                                ),
                                project_badge=project_badge(snapshot, project),
                            ),
                            phase_target in active_marks,
                        ),
                        (jump_hints or {}).get(phase_target),
                    ),
                    id=phase_id,
                )
            )
    if not snapshot.epics:
        options.append(
            Option(single_line_text("  No epic beads", style="dim"), disabled=True)
        )
    return options, rows


def _section_option(label: str, count: int, *, triage_count: int = 0) -> Option:
    text = single_line_text()
    text.append(f"── {label} ", style=f"bold {ARTIFACTS_ACCENTS['beads']}")
    text.append(f"({count}) ", style="dim")
    if label == "Tasks" and triage_count:
        text.append(f"· ✦ {triage_count} awaiting triage ", style="bold #D787FF")
    elif label == "Epics":
        text.append("· ", style="dim")
        text.append(BLOCKED_STATE_GLYPH, style="bold #FF5F5F")
        text.append(" blocked ", style="dim")
        text.append(READY_STATE_GLYPH, style="bold #5FD787")
        text.append(" ready ", style="dim")
        text.append(LAUNCHED_STATE_GLYPH, style="bold #00D7AF")
        text.append(" launched ", style="dim")
    text.append("─" * 8, style="dim #5F5F87")
    return Option(text, id=f"header:{label.casefold()}", disabled=True)


__all__ = [
    "BeadRow",
    "BeadRowKind",
    "bead_row_target",
    "build_bead_options",
    "row_option_id",
]
