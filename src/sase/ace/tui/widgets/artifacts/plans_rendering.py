"""Pure Rich renderable builders for the document-only Plans pane."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from rich.text import Text

from sase.bead_status_presentation import bead_status_presentation
from sase.core.time import parse_local
from sase.plan_search.model import PlanSearchMatch

from ...keymaps import KeymapRegistry, key_display_name
from .plans_data import ActivePlanDocument, PlanProposal, PlansSnapshot
from .shell import (
    ArtifactsPaneState,
    build_footer_hints,
    build_shell_scope,
    build_state_badge,
)
from .types import ARTIFACTS_ACCENTS


def build_plans_scope(
    registry: KeymapRegistry,
    *,
    project_scope: str | None,
    project_display_name: str | None,
    filter_tokens: tuple[str, ...] = (),
    provider_label: str = "Plan",
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> Text:
    return build_shell_scope(
        label=provider_label,
        accent=accent,
        scope_label=project_display_name or project_scope or "All projects",
        change_hint=f"{key_display_name(registry.app.pick_artifacts_project)} change",
        filter_tokens=filter_tokens,
    )


def build_plans_status(
    snapshot: PlansSnapshot | None,
    *,
    loading: bool,
    load_error: str | None,
    matched_counts: Mapping[str, int] | None = None,
    archive_total: int | None = None,
    archive_coverage_label: str | None = None,
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> Text:
    text = Text()
    if loading and snapshot is None:
        text.append("Loading…", style="bold #FFD700")
    elif load_error and snapshot is None:
        text.append(load_error, style="bold #FF5F5F")
    elif snapshot is None:
        text.append("Plans have not loaded yet", style="dim")
    else:
        if loading or load_error:
            # A refresh is running or failed, but cached rows from this
            # scope remain: preserve them and overlay a stale badge instead
            # of blanking the counts.
            text.append_text(
                build_state_badge(
                    ArtifactsPaneState.STALE,
                    error_message=load_error if not loading else None,
                )
            )
            text.append("  ·  ", style="dim")
        if snapshot.project is None:
            text.append(f"{len(snapshot.projects)} projects", style="bold white")
            text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts, "proposal", len(snapshot.proposals), "proposals"
            ),
            style="#FFD700",
        )
        text.append("  ·  ", style="dim")
        text.append(
            _matched_count_label(
                matched_counts, "active", len(snapshot.active), "active"
            ),
            style=accent,
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


def build_plans_hints(
    registry: KeymapRegistry,
    *,
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> Text:
    keymap = registry.app
    parts = (
        (key_display_name(keymap.plans_next), "next"),
        (key_display_name(keymap.plans_prev), "prev"),
        (key_display_name(keymap.plans_view_selected), "view"),
        (key_display_name(keymap.edit_query), "filter"),
        (key_display_name(keymap.plans_approve), "approve"),
        (key_display_name(keymap.plans_reject), "reject"),
        (key_display_name(keymap.plans_refresh), "refresh"),
    )
    return build_footer_hints(parts, accent=accent)


def build_empty_plan_detail(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    load_error: str | None,
    has_active_filter: bool = False,
    matched_total: int | None = None,
) -> str:
    if loading and snapshot is None:
        return "# Plans\n\nLoading plan documents…"
    if load_error and snapshot is None:
        return f"# Plans unavailable\n\n{load_error}"
    if has_active_filter and matched_total == 0:
        return (
            "# No matches\n\n"
            "No plan documents match the active filter. Press the filter key "
            "to edit or clear it."
        )
    message = (
        "Select a proposal, active plan, or archived plan from all enabled projects."
        if project_scope is None
        else "Select a proposal, active plan, or archived plan."
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
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> Text:
    text = single_line_text()
    text.append("◆ ", style="bold #FFD700")
    text.append(proposal.title, style="bold white")
    text.append(f"  {proposal.tier}", style=f"bold {accent}")
    age = _compact_inventory_age(proposal.age)
    if age:
        text.append(f"  {age}", style="dim")
    _append_project_badge(text, project_badge)
    return text


def active_plan_text(
    active: ActivePlanDocument,
    *,
    project_badge: str | None = None,
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> Text:
    """Render a plan document with its owning live bead metadata."""
    document = active.document
    owner = active.owner
    text = single_line_text("▤ ", style=f"bold {accent}")
    text.append(_document_title(document.path, document.frontmatter), style="white")
    tier = document.frontmatter.get("tier") or (
        owner.bead_tier.value if owner.bead_tier is not None else ""
    )
    if tier:
        text.append(f"  {tier}", style=f"bold {accent}")
    presentation = bead_status_presentation(owner.bead_status)
    text.append(f"  {owner.bead_id} ", style="bold #FFD700")
    text.append(presentation.tui_glyph, style=presentation.rich_style)
    text.append(
        f" {owner.bead_status.value.replace('_', ' ')}", style=presentation.rich_style
    )
    timestamp = (
        document.frontmatter.get("create_time", "")
        or document.frontmatter.get("created_at", "")
        or owner.bead_created_at
    )
    age = _compact_relative_age(timestamp)
    if age:
        text.append(f"  {age}", style="dim")
    _append_project_badge(text, project_badge)
    return text


def archive_text(
    match: PlanSearchMatch,
    *,
    project_badge: str | None = None,
    accent: str = ARTIFACTS_ACCENTS["plans"],
) -> Text:
    plan = match.plan
    text = single_line_text("▤ ", style="bold #00D7AF")
    text.append(plan.title or plan.name, style="white")
    text.append(f"  {plan.kind}", style=f"bold {accent}")
    if plan.status:
        status_style = "#5FD787" if plan.status in {"done", "approved"} else "#FFD700"
        text.append(f"  {plan.status}", style=f"bold {status_style}")
    if plan.created_at:
        text.append(f"  {_compact_plan_date(plan.created_at)}", style="dim")
    _append_project_badge(text, project_badge)
    return text


def single_line_text(text: str = "", *, style: str = "") -> Text:
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def project_badge(snapshot: PlansSnapshot, project: str) -> str | None:
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


def _append_project_badge(text: Text, project_badge: str | None) -> None:
    if project_badge:
        text.append(f"  [{project_badge}]", style="dim")


def _document_title(path: str, frontmatter: dict[str, str]) -> str:
    return (
        frontmatter.get("title")
        or Path(path).stem.replace("_", " ").replace("-", " ").title()
    )


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
    parsed = parse_local(timestamp)
    if parsed is None:
        return date
    return parsed.strftime("%m-%d")


__all__ = [
    "active_plan_text",
    "archive_text",
    "build_empty_plan_detail",
    "build_plans_hints",
    "build_plans_scope",
    "build_plans_status",
    "project_badge",
    "proposal_text",
    "single_line_text",
]
