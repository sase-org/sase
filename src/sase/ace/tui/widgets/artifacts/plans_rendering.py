"""Pure Rich renderable builders for the Artifacts Plans pane."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from rich.text import Text

from sase.bead.model import Issue, Status
from sase.plan_search.model import PlanSearchMatch

from ...keymaps import KeymapRegistry, key_display_name, leader_key_display
from .plans_data import PlanProposal, PlansSnapshot
from .types import ARTIFACTS_ACCENTS


BLOCKED_STATE_GLYPH = "⊜"
READY_STATE_GLYPH = "►"
LAUNCHED_STATE_GLYPH = "▶"
EMPTY_STATE_GLYPH = "·"


def build_plans_scope(
    registry: KeymapRegistry,
    *,
    project_scope: str | None,
    project_display_name: str | None,
    filter_tokens: tuple[str, ...] = (),
) -> Text:
    """Build the pane's project-scope header."""
    text = Text()
    text.append(
        " Plans ",
        style=f"bold #1a1a1a on {ARTIFACTS_ACCENTS['plans']}",
    )
    text.append("  Project scope  ", style="dim")
    label = project_display_name or project_scope or "All projects"
    text.append(f" {label} ", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    text.append("  ·  ", style="dim")
    text.append(
        f"{key_display_name(registry.app.pick_artifacts_project)} change",
        style="dim",
    )
    for token in filter_tokens:
        text.append("  ·  ", style="dim")
        text.append(token, style="dim #87D7FF")
    return text


def build_plans_status(
    snapshot: PlansSnapshot | None,
    *,
    loading: bool,
    load_error: str | None,
    matched_counts: Mapping[str, int] | None = None,
    archive_total: int | None = None,
    archive_coverage_label: str | None = None,
) -> Text:
    """Build the snapshot summary shown above the plan list."""
    text = Text()
    if loading:
        text.append("Loading…", style="bold #FFD700")
    elif load_error:
        text.append(load_error, style="bold #FF5F5F")
    elif snapshot is None:
        text.append("Plans have not loaded yet", style="dim")
    else:
        phase_count = sum(len(phases) for phases in snapshot.phases_by_epic.values())
        if snapshot.project is None:
            text.append(f"{len(snapshot.projects)} projects", style="bold white")
            text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts,
                "proposal",
                len(snapshot.proposals),
                "proposals",
            ),
            style="#FFD700",
        )
        text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts,
                "epic",
                len(snapshot.epics),
                "epics",
            ),
            style=ARTIFACTS_ACCENTS["plans"],
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
        text.append("  ·  ", style="dim")
        archive_label = _matched_count_label(
            matched_counts,
            "archive",
            len(snapshot.archive) if archive_total is None else archive_total,
            "archived",
        )
        if archive_coverage_label is not None:
            if archive_coverage_label:
                archive_label += f" ({archive_coverage_label})"
        elif snapshot.archive_truncated:
            archive_label += " (newest shown)"
        text.append(archive_label, style="#00D7AF")
        if snapshot.errors:
            text.append("  ·  ", style="dim")
            error_projects = ", ".join(
                snapshot.display_names.get(project, project)
                for project in sorted(snapshot.errors)
            )
            text.append(f"Load errors: {error_projects}", style="bold #FF5F5F")
    return text


def build_plans_hints(registry: KeymapRegistry) -> Text:
    """Build the configured action hints shown below the plan panels."""
    keymap = registry.app
    parts = (
        (key_display_name(keymap.plans_next), "next"),
        (key_display_name(keymap.plans_prev), "prev"),
        (key_display_name(keymap.plans_view_selected), "view"),
        (leader_key_display(registry, "edit_query"), "filter"),
        (key_display_name(keymap.plans_expand), "expand"),
        (key_display_name(keymap.plans_collapse), "collapse"),
        (key_display_name(keymap.plans_cycle_status), "status"),
        (key_display_name(keymap.plans_edit_bead), "edit"),
        (key_display_name(keymap.plans_launch_epic), "work"),
        (key_display_name(keymap.plans_approve), "approve"),
        (key_display_name(keymap.plans_reject), "reject"),
        (key_display_name(keymap.plans_open_bug), "bug"),
        (key_display_name(keymap.plans_refresh), "refresh"),
    )
    text = Text(justify="center")
    for index, (key, label) in enumerate(parts):
        if index:
            text.append("  ", style="dim")
        text.append(key, style=f"bold {ARTIFACTS_ACCENTS['plans']}")
        text.append(f" {label}", style="dim")
    return text


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


def build_empty_plan_detail(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    load_error: str | None,
) -> str:
    """Build the detail placeholder and any project load warnings."""
    if loading:
        return "# Plans\n\nLoading proposals, beads, and committed plans…"
    if load_error:
        return f"# Plans unavailable\n\n{load_error}"
    message = (
        "Select a proposal, bead, or archived plan from all enabled projects."
        if project_scope is None
        else "Select a proposal, bead, or archived plan."
    )
    lines = ["# Plans", "", message]
    if snapshot is not None and snapshot.errors:
        lines.extend(["", "## Load warnings", ""])
        for project, error in sorted(snapshot.errors.items()):
            lines.append(f"- **{project}:** {error}")
    return "\n".join(lines)


def proposal_text(
    proposal: PlanProposal,
    *,
    project_badge: str | None = None,
) -> Text:
    """Render one pending proposal row."""
    text = single_line_text()
    text.append("◆ ", style="bold #FFD700")
    text.append(proposal.title, style="bold white")
    text.append(f"  {proposal.tier}", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    age = _compact_inventory_age(proposal.age)
    if age:
        text.append(f"  {age}", style="dim")
    _append_project_badge(text, project_badge)
    return text


def epic_text(
    epic: Issue,
    phases: tuple[Issue, ...],
    *,
    expanded: bool,
    project: str,
    ready_ids: frozenset[tuple[str, str]],
    blocked_ids: frozenset[tuple[str, str]],
    project_badge: str | None = None,
) -> Text:
    """Render one expandable epic row."""
    text = single_line_text()
    text.append(
        "▾ " if expanded else "▸ ",
        style=f"bold {ARTIFACTS_ACCENTS['plans']}",
    )
    text.append(_status_glyph(epic.status), style=_status_style(epic.status))
    text.append(f" {epic.id} ", style="bold #FFD700")
    closed = sum(phase.status == Status.CLOSED for phase in phases)
    text.append(f"{closed}/{len(phases)} ", style="#87D7FF")
    issue_key = (project, epic.id)
    state_glyph, state_style = _state_glyph(
        issue_key,
        ready_ids=ready_ids,
        blocked_ids=blocked_ids,
        launched=epic.is_ready_to_work,
    )
    text.append(state_glyph, style=state_style)
    text.append(" ")
    text.append(epic.title, style="bold white")
    age = _compact_relative_age(epic.created_at)
    if age:
        text.append(f"  {age}", style="dim")
    _append_project_badge(text, project_badge)
    return text


def phase_text(
    phase: Issue,
    *,
    project: str,
    ready_ids: frozenset[tuple[str, str]],
    blocked_ids: frozenset[tuple[str, str]],
) -> Text:
    """Render one expanded epic phase row."""
    text = single_line_text("↳ ", style=f"dim {ARTIFACTS_ACCENTS['plans']}")
    text.append(_status_glyph(phase.status), style=_status_style(phase.status))
    text.append(f" {phase.id} ", style="bold #FFD700")
    issue_key = (project, phase.id)
    state_glyph, state_style = _state_glyph(
        issue_key,
        ready_ids=ready_ids,
        blocked_ids=blocked_ids,
    )
    text.append(state_glyph, style=state_style)
    text.append(" ")
    text.append(phase.title, style="white")
    return text


def archive_text(
    match: PlanSearchMatch,
    *,
    project_badge: str | None = None,
) -> Text:
    """Render one archived plan row."""
    plan = match.plan
    text = single_line_text("▤ ", style="bold #00D7AF")
    text.append(plan.title or plan.name, style="white")
    text.append(f"  {plan.kind}", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    if plan.status:
        status_style = "#5FD787" if plan.status in {"done", "approved"} else "#FFD700"
        text.append(f"  {plan.status}", style=f"bold {status_style}")
    if plan.created_at:
        text.append(f"  {_compact_plan_date(plan.created_at)}", style="dim")
    _append_project_badge(text, project_badge)
    return text


def single_line_text(text: str = "", *, style: str = "") -> Text:
    """Return a compact row label with one-line Rich ``Text`` intent.

    Textual 8 converts option prompts to ``Content`` and drops these Rich wrapping
    attributes, so the owning OptionList's CSS enforces the one-line contract.
    """
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def project_badge(snapshot: PlansSnapshot, project: str) -> str | None:
    """Return a project label only when browsing all projects."""
    if snapshot.project is not None:
        return None
    return snapshot.display_names.get(project, project)


def _append_project_badge(text: Text, project_badge: str | None) -> None:
    if project_badge:
        text.append(f"  [{project_badge}]", style="dim")


def _state_glyph(
    issue_key: tuple[str, str],
    *,
    ready_ids: frozenset[tuple[str, str]],
    blocked_ids: frozenset[tuple[str, str]],
    launched: bool = False,
) -> tuple[str, str]:
    """Return the fixed-width readiness state column for a bead row."""
    if issue_key in blocked_ids:
        return BLOCKED_STATE_GLYPH, "bold #FF5F5F"
    if issue_key in ready_ids:
        return READY_STATE_GLYPH, "bold #5FD787"
    if launched:
        return LAUNCHED_STATE_GLYPH, "bold #00D7AF"
    return EMPTY_STATE_GLYPH, "dim"


def _compact_inventory_age(age: str) -> str:
    value = age.strip()
    if value == "just now":
        return "now"
    return value.removesuffix(" ago")


def _compact_relative_age(timestamp: str) -> str:
    if not timestamp.strip():
        return ""
    try:
        created = datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return ""

    from sase.core.time import get_timezone, local_now, to_local

    if created.tzinfo is None:
        created = created.replace(tzinfo=get_timezone())
    elapsed_seconds = max(0, int((local_now() - to_local(created)).total_seconds()))
    if elapsed_seconds < 60:
        return "now"
    minutes = elapsed_seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def _compact_plan_date(timestamp: str) -> str:
    date = timestamp.strip()[:10]
    if len(date) == 10 and date[4] == "-" and date[7] == "-":
        return date[5:]
    return date


def _status_glyph(status: Status) -> str:
    return {
        Status.OPEN: "○",
        Status.IN_PROGRESS: "◐",
        Status.CLOSED: "●",
    }[status]


def _status_style(status: Status) -> str:
    return {
        Status.OPEN: "bold #87D7FF",
        Status.IN_PROGRESS: "bold #FFD700",
        Status.CLOSED: "bold #5FD787",
    }[status]
