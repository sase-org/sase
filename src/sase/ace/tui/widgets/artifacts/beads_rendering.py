"""Pure Rich renderable builders for the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text

from sase.bead.model import Issue, IssueType, PhaseSize, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_RICH_STYLE,
    POST_CLOSE_RICH_STYLE,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
)
from sase.bead.reopen_presentation import REOPEN_RICH_STYLE, reopen_badge
from sase.bead.snooze_presentation import SNOOZE_ACCENT, snooze_wake_chip
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import (
    bead_created_chip,
    bead_updated_chip,
    suppress_duplicate_updated,
)
from sase.bead_type_presentation import bead_type_presentation
from sase.phase_size_presentation import phase_size_chip

from ...keymaps import KeymapRegistry, key_display_name
from .beads_data import BeadsSnapshot
from .beads_data_models import ExternalIssueLink
from .types import ARTIFACTS_ACCENTS, EXTERNAL_ACCENT

BLOCKED_STATE_GLYPH = "⊜"
READY_STATE_GLYPH = "►"
LAUNCHED_STATE_GLYPH = "▶"
EMPTY_STATE_GLYPH = "·"


def build_beads_scope(
    registry: KeymapRegistry,
    *,
    project_scope: str | None,
    project_display_name: str | None,
    filter_tokens: tuple[str, ...] = (),
) -> Text:
    text = Text()
    accent = ARTIFACTS_ACCENTS["beads"]
    text.append(" Bead ", style=f"bold #1a1a1a on {accent}")
    text.append("  Project scope  ", style="dim")
    text.append(
        f" {project_display_name or project_scope or 'All projects'} ",
        style=f"bold {accent}",
    )
    text.append("  ·  ", style="dim")
    text.append(
        f"{key_display_name(registry.app.pick_artifacts_project)} change",
        style="dim",
    )
    for token in filter_tokens:
        text.append("  ·  ", style="dim")
        text.append(token, style="dim #87D7FF")
    return text


def build_beads_status(
    snapshot: BeadsSnapshot | None,
    *,
    loading: bool,
    load_error: str | None,
    matched_counts: Mapping[str, int] | None = None,
    matched_triage_count: int | None = None,
) -> Text:
    text = Text()
    if loading:
        text.append("Loading…", style="bold #FFD700")
    elif load_error:
        text.append(load_error, style="bold #FF5F5F")
    elif snapshot is None:
        text.append("Beads have not loaded yet", style="dim")
    else:
        phase_count = sum(len(phases) for phases in snapshot.phases_by_epic.values())
        if snapshot.project is None:
            text.append(f"{len(snapshot.projects)} projects", style="bold white")
            text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts,
                "task",
                len(snapshot.tasks),
                "tasks",
            ),
            style=ARTIFACTS_ACCENTS["beads"],
        )
        text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts,
                "epic",
                len(snapshot.epics),
                "epics",
            ),
            style="#FFD700",
        )
        text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts,
                "phase",
                phase_count,
                "phases",
            ),
            style="#87D7FF",
        )
        triage_count = (
            matched_triage_count
            if matched_counts is not None and matched_triage_count is not None
            else len(snapshot.triage_gates)
        )
        if triage_count:
            text.append("  ·  ", style="dim")
            text.append(
                f"✦ {triage_count} awaiting triage",
                style=f"bold {ARTIFACTS_ACCENTS['beads']}",
            )
        _append_external_status(text, snapshot)
        if snapshot.errors:
            text.append("  ·  ", style="dim")
            labels = ", ".join(
                snapshot.display_names.get(project, project)
                for project in sorted(snapshot.errors)
            )
            text.append(f"Load errors: {labels}", style="bold #FF5F5F")
    return text


def build_beads_hints(registry: KeymapRegistry) -> Text:
    keymap = registry.app
    parts = (
        (key_display_name(keymap.beads_next), "next"),
        (key_display_name(keymap.beads_prev), "prev"),
        (key_display_name(keymap.beads_view_selected), "view"),
        (key_display_name(keymap.beads_filters), "filter"),
        (key_display_name(keymap.beads_expand), "expand"),
        (key_display_name(keymap.beads_collapse), "collapse"),
        (key_display_name(keymap.beads_refresh), "refresh"),
    )
    text = Text(justify="center")
    for index, (key, label) in enumerate(parts):
        if index:
            text.append("  ", style="dim")
        text.append(key, style=f"bold {ARTIFACTS_ACCENTS['beads']}")
        text.append(f" {label}", style="dim")
    return text


def build_empty_bead_detail(
    snapshot: BeadsSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    load_error: str | None,
) -> str:
    if loading:
        return "# Beads\n\nLoading task, epic, and phase beads…"
    if load_error:
        return f"# Beads unavailable\n\n{load_error}"
    if snapshot is not None and not snapshot.tasks and not snapshot.epics:
        return (
            "# No beads yet\n\n"
            "Agents use `/sase_new_task` before creating a sized draft task, then "
            "mark it ready for TaskTriage when it is ready to launch.\n\n"
            "TaskTriage decisions can launch or close the task here in the Beads pane."
        )
    message = (
        "Select a bead from all enabled projects."
        if project_scope is None
        else "Select a task, epic, or phase bead."
    )
    lines = ["# Beads", "", message]
    if snapshot is not None and snapshot.errors:
        lines.extend(["", "## Load warnings", ""])
        for project, error in sorted(snapshot.errors.items()):
            label = snapshot.display_names.get(project, project)
            lines.append(f"- **{label}:** {error}")
    return "\n".join(lines)


def task_text(
    task: Issue,
    *,
    triage: bool,
    plan_link: bool,
    project_badge: str | None = None,
    external_links: tuple[ExternalIssueLink, ...] = (),
) -> Text:
    return _bead_text(
        task,
        triage=triage,
        plan_link=plan_link,
        project_badge=project_badge,
        external_links=external_links,
    )


def epic_text(
    epic: Issue,
    phases: tuple[Issue, ...],
    *,
    expanded: bool,
    project: str,
    ready_ids: frozenset[tuple[str, str]],
    blocked_ids: frozenset[tuple[str, str]],
    plan_link: bool,
    project_badge: str | None = None,
    external_links: tuple[ExternalIssueLink, ...] = (),
) -> Text:
    text = single_line_text()
    text.append(
        "▾ " if expanded else "▸ ",
        style=f"bold {ARTIFACTS_ACCENTS['beads']}",
    )
    presentation = bead_type_presentation(epic.issue_type)
    text.append(f"{presentation.glyph} ", style=presentation.rich_style)
    if plan_link:
        text.append("▤ ", style="bold #AF87FF")
    text.append(f"{epic.id} ", style="bold #FFD700")
    text.append(epic.title, style="bold white")
    _append_external_issue_chip(text, external_links)
    text.append("  ")
    _append_status(text, epic.status)
    closed = sum(phase.status is Status.CLOSED for phase in phases)
    text.append(f"  {closed}/{len(phases)} phases", style="#87D7FF")
    state_glyph, state_style = _state_glyph(
        (project, epic.id),
        ready_ids=ready_ids,
        blocked_ids=blocked_ids,
        launched=epic.is_ready_to_work,
    )
    text.append(f"  {state_glyph}", style=state_style)
    _append_metadata(text, epic, project_badge)
    return text


def phase_text(
    phase: Issue,
    *,
    plan_link: bool,
    project_badge: str | None = None,
    external_links: tuple[ExternalIssueLink, ...] = (),
) -> Text:
    text = single_line_text("  ")
    presentation = bead_type_presentation(phase.issue_type)
    text.append(f"{presentation.glyph} ", style=presentation.rich_style)
    if plan_link:
        text.append("▤ ", style="bold #AF87FF")
    text.append(f"{phase.id} ", style="bold #FFD700")
    text.append(phase.title, style="white")
    _append_external_issue_chip(text, external_links)
    text.append("  ")
    _append_status(text, phase.status)
    text.append("  ")
    text.append_text(phase_size_chip(phase.size or PhaseSize.SMALL))
    _append_metadata(text, phase, project_badge)
    return text


def project_badge(snapshot: BeadsSnapshot, project: str) -> str | None:
    if snapshot.project is not None:
        return None
    return snapshot.display_names.get(project, project)


def _matched_count_label(
    matched_counts: Mapping[str, int] | None,
    kind: str,
    total: int,
    noun: str,
) -> str:
    count = str(total)
    if matched_counts is not None:
        count = f"{matched_counts.get(kind, 0)}/{total}"
    return f"{count} {noun}"


def _append_external_status(text: Text, snapshot: BeadsSnapshot) -> None:
    linked_count = sum(len(links) for links in snapshot.external_links.values())
    unmirrored_count = sum(snapshot.external_unmirrored_counts.values())
    stale_count = sum(
        link.stale for links in snapshot.external_links.values() for link in links
    )
    drift_count = sum(
        link.drift for links in snapshot.external_links.values() for link in links
    )
    listing_available = any(
        cache.capabilities.listing for cache in snapshot.external_projects.values()
    )
    external_errors = tuple(
        project for project, cache in snapshot.external_projects.items() if cache.error
    )
    if linked_count or unmirrored_count or stale_count or drift_count:
        text.append("  ·  ", style="dim")
        text.append(f"{linked_count} issue links", style=EXTERNAL_ACCENT)
        if unmirrored_count:
            text.append(f"  ·  {unmirrored_count} remote-only", style="dim")
        if stale_count:
            text.append(f"  ·  {stale_count} stale", style=f"bold {EXTERNAL_ACCENT}")
        if drift_count:
            text.append(f"  ·  {drift_count} drift", style=f"bold {EXTERNAL_ACCENT}")
    elif snapshot.external_projects and not listing_available:
        text.append("  ·  ", style="dim")
        text.append("external issues unavailable", style="dim")
    if external_errors:
        text.append("  ·  ", style="dim")
        labels = ", ".join(
            snapshot.display_names.get(project, project)
            for project in sorted(external_errors)
        )
        text.append(f"Issue errors: {labels}", style=f"bold {EXTERNAL_ACCENT}")


def single_line_text(text: str = "", *, style: str = "") -> Text:
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def _bead_text(
    issue: Issue,
    *,
    triage: bool,
    plan_link: bool,
    project_badge: str | None,
    external_links: tuple[ExternalIssueLink, ...] = (),
) -> Text:
    presentation = bead_type_presentation(issue.issue_type)
    text = single_line_text()
    text.append(f"{presentation.glyph} ", style=presentation.rich_style)
    if triage:
        text.append("✦ ", style=f"bold {ARTIFACTS_ACCENTS['beads']}")
    if plan_link:
        text.append("▤ ", style="bold #AF87FF")
    text.append(f"{issue.id} ", style="bold #FFD700")
    text.append(issue.title, style="white")
    _append_external_issue_chip(text, external_links)
    if badge := plus_one_badge(issue.plus_one_count):
        text.append(f"  [{badge}]", style=PLUS_ONE_RICH_STYLE)
    if reopen := reopen_badge(len(issue.close_history)):
        text.append(f"  [{reopen}]", style=REOPEN_RICH_STYLE)
    if post_close := post_close_plus_one_badge(post_close_plus_one_count(issue)):
        text.append(f"  [{post_close}]", style=POST_CLOSE_RICH_STYLE)
    text.append("  ")
    _append_status(text, issue.status)
    if issue.size is not None:
        text.append("  ")
        text.append_text(phase_size_chip(issue.size))
    _append_metadata(text, issue, project_badge)
    return text


def _append_external_issue_chip(
    text: Text,
    links: tuple[ExternalIssueLink, ...],
) -> None:
    if not links:
        return
    link = _primary_external_issue_link(links)
    glyph = (
        "?"
        if link.stale
        else "●"
        if link.issue and link.issue.state == "closed"
        else "○"
    )
    label = f"{glyph}#{link.issue_id}"
    text.append("  ")
    if link.stale or link.drift:
        text.append(f" {label} ", style=f"bold #1a1a1a on {EXTERNAL_ACCENT}")
    else:
        text.append(label, style=f"bold {EXTERNAL_ACCENT}")
    if len(links) > 1:
        text.append(f"+{len(links) - 1}", style="dim")


def _primary_external_issue_link(
    links: tuple[ExternalIssueLink, ...],
) -> ExternalIssueLink:
    return sorted(
        links,
        key=lambda link: (
            not link.stale,
            not link.drift,
            0 if link.relation == "mirrored" else 1,
            link.project,
            link.issue_id,
        ),
    )[0]


def _append_status(text: Text, status: Status) -> None:
    presentation = bead_status_presentation(status)
    text.append(presentation.tui_glyph, style=presentation.rich_style)
    text.append(
        f" {presentation.label.replace('_', ' ').lower()}",
        style=presentation.rich_style,
    )


def _append_metadata(text: Text, issue: Issue, project_label: str | None) -> None:
    if issue.snooze is not None and (wake := snooze_wake_chip(issue.snooze.until)):
        text.append(f"  {wake}", style=SNOOZE_ACCENT)
    if issue.assignee:
        text.append(f"  {issue.assignee}", style="dim")
    if created := bead_created_chip(issue.created_at):
        text.append("  ")
        text.append_text(created)
    if not suppress_duplicate_updated(issue.created_at, issue.updated_at):
        if updated := bead_updated_chip(issue.updated_at):
            text.append("  ")
            text.append_text(updated)
    if project_label:
        text.append(f"  [{project_label}]", style="dim")


def _state_glyph(
    issue_key: tuple[str, str],
    *,
    ready_ids: frozenset[tuple[str, str]],
    blocked_ids: frozenset[tuple[str, str]],
    launched: bool,
) -> tuple[str, str]:
    if issue_key in blocked_ids:
        return BLOCKED_STATE_GLYPH, "bold #FF5F5F"
    if issue_key in ready_ids:
        return READY_STATE_GLYPH, "bold #5FD787"
    if launched:
        return LAUNCHED_STATE_GLYPH, "bold #00D7AF"
    return EMPTY_STATE_GLYPH, "dim"


__all__ = [
    "BLOCKED_STATE_GLYPH",
    "LAUNCHED_STATE_GLYPH",
    "READY_STATE_GLYPH",
    "build_beads_hints",
    "build_beads_scope",
    "build_beads_status",
    "build_empty_bead_detail",
    "epic_text",
    "phase_text",
    "project_badge",
    "single_line_text",
    "task_text",
]
