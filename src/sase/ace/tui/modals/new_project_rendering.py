"""Rich, literal-text renderers for the New Project wizard."""

from __future__ import annotations

import re
from typing import Any

from rich.text import Text

from .new_project_source_model import SourceRow

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_source_text(value: object) -> str:
    """Remove control characters from provider-controlled text."""
    return _CONTROL_RE.sub("", str(value or ""))


def render_stepper(stage: str) -> Text:
    """Render the three visible wizard steps for the current stage."""
    steps = (("source", "Source"), ("configure", "Configure"), ("review", "Review"))
    progress = {
        "source": 0,
        "configure": 1,
        "review": 2,
        "progress": 3,
        "ready": 3,
        "failed": 3,
    }
    active = progress.get(stage, 0)
    text = Text()
    for index, (_key, label) in enumerate(steps):
        if index:
            text.append("  ›  ", style="dim #777777")
        if index < active:
            text.append(f"✓ {label}", style="bold #00D7AF")
        elif index == active:
            text.append(f"● {label}", style="bold #FFAF5F")
        else:
            text.append(f"○ {label}", style="dim #888888")
    return text


def render_source_row(row: SourceRow) -> Text:
    """Render a candidate row with the plan's Source glyphs."""
    glyphs = {
        "create": "✚",
        "resume": "↻",
        "local": "⌂",
        "suggested": "○",
        "linked": "⇄",
        "disabled": "◐",
        "paste": "↵",
        "owner_error": "⚠",
        "owner_fetching": "◌",
        "search_only": "┄",
    }
    if row.group == "search_only" and row.hidden_reason == "enabled_project":
        project_name = clean_source_text(
            row.data.get("project_name") or row.data.get("project_key") or row.display
        )
        row_text = Text()
        row_text.append("●  ", style="#00D7AF")
        row_text.append(clean_source_text(row.display), style="bold")
        row_text.append(
            f"  already the project {project_name} — ⏎ show it", style="dim"
        )
        return row_text
    row_text = Text()
    glyph = glyphs.get(row.group, "○")
    glyph_style = "#FFAF5F" if row.group == "paste" else "#888888"
    if row.group == "owner_error":
        glyph_style = "#FFAF5F"
    row_text.append(f"{glyph}  ", style=glyph_style)
    row_text.append(clean_source_text(row.display), style="bold")
    details: list[str] = []
    for key in ("visibility", "pushed_at", "local_path", "description"):
        value = clean_source_text(row.data.get(key, ""))
        if key == "description" and len(value) > 54:
            value = value[:53] + "…"
        if value:
            details.append(value)
    if row.group == "resume":
        status = clean_source_text(
            row.data.get("status") or row.data.get("journal_status") or "stopped"
        )
        details.insert(0, f"{status} · ⏎ resume")
    if row.group == "disabled":
        details.append("⏎ re-enables")
    if details:
        row_text.append("  " + " · ".join(details), style="dim")
    return row_text


def render_no_owners_detail(provider_display: str) -> Text:
    """Render the Source detail card when no provider owners are known."""
    text = Text()
    provider = clean_source_text(provider_display) or "GitHub"
    text.append(f"No {provider} owners yet", style="bold #FFAF5F")
    text.append(
        "\nPaste owner/repo, or add owners to github_orgs in Config Center.",
        style="dim",
    )
    return text


def _probe_status_word(probe: Any | None, *, checking: bool) -> str:
    """Render the plan's detail status wording for one provider probe."""
    if checking:
        return "◌ checking…"
    if probe is None:
        return "? unknown"
    managed = getattr(probe, "sase_managed", None)
    if managed is True:
        return "✓ managed"
    if managed is False:
        return "○ will be set up"
    return "? unknown"


def render_source_detail(
    row: SourceRow | None,
    *,
    workflow_type: str,
    parsed: Any | None = None,
    probe: Any | None = None,
    checking: bool = False,
    probe_error: str = "",
    project_accent_color: str = "",
    collapsed: bool = False,
) -> Text:
    """Render local identity facts followed by a live provider probe.

    When *collapsed* is true (short terminals), render one summary line
    instead of the full card.
    """
    text = Text()
    if row is None:
        text.append(
            "Select a repository to preview its checkout and project identity.",
            style="dim",
        )
        return text
    title = clean_source_text(row.display)
    if collapsed and not row.is_error and row.group != "create":
        visibility = clean_source_text(getattr(probe, "visibility", "") or "")
        parts = [title]
        if visibility:
            parts.append(visibility)
        if probe is not None or checking:
            parts.append(_probe_status_word(probe, checking=checking))
        elif probe_error:
            parts.append("? unknown")
        text.append(" · ".join(parts), style="dim")
        return text
    text.append(title, style="bold #FFAF5F")
    if row.group == "create":
        text.append("\nStart a new remote repository on ", style="dim")
        text.append(clean_source_text(workflow_type) or "this provider")
        text.append("\nDescribe it, then review the exact create plan.", style="dim")
        return text
    if row.is_error:
        text.append("\nProvider owner unavailable", style="bold #FFAF5F")
        message = clean_source_text(row.data.get("message", ""))
        if message:
            text.append("\n" + message, style="dim")
        return text
    checkout = clean_source_text(
        row.data.get("local_path")
        or row.data.get("path")
        or getattr(parsed, "checkout_dir", "")
    )
    project_name = clean_source_text(getattr(parsed, "project_name_base", ""))
    project_key = clean_source_text(getattr(parsed, "project_key_base", ""))
    if checkout:
        text.append("\nCheckout  ", style="dim")
        text.append(checkout)
        text.append(
            "  " + ("already cloned" if row.group == "local" else "will clone"),
            style="dim",
        )
    if project_name or project_key:
        text.append("\nProject   ", style="dim")
        text.append(project_name or "?", style="bold")
        if project_key:
            text.append(f"  key {project_key}", style="dim")
        if project_accent_color:
            text.append("  ■", style=project_accent_color)
        text.append("  ● enabled", style="#00D7AF")
    if probe is not None:
        visibility = clean_source_text(getattr(probe, "visibility", ""))
        branch = clean_source_text(getattr(probe, "default_branch", ""))
        remote_details = [part for part in (visibility, branch) if part]
        remote_details.append(_probe_status_word(probe, checking=False))
        can_push = getattr(probe, "can_push", None)
        if can_push is not None:
            remote_details.append("push allowed" if can_push else "no push")
        if remote_details:
            text.append("\nRemote    ", style="dim")
            text.append(" · ".join(remote_details))
        probe_message = clean_source_text(getattr(probe, "message", ""))
        if probe_message:
            text.append("\n" + probe_message, style="dim")
    elif checking:
        text.append("\n◌ checking…", style="dim")
    elif probe_error:
        text.append("\n? " + clean_source_text(probe_error), style="dim")
    elif not row.ref:
        text.append(f"\n{clean_source_text(workflow_type)}", style="dim")
    return text


__all__ = [
    "clean_source_text",
    "render_no_owners_detail",
    "render_source_detail",
    "render_source_row",
    "render_stepper",
]
