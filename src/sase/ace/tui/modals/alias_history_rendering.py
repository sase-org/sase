"""Pure rendering helpers for the Launch Control alias-history panel.

No Textual imports beyond :mod:`rich.text` — every function here takes typed
view models and returns a :class:`~rich.text.Text` or plain string, so the
whole module is cheaply unit-testable without mounting the modal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rich.text import Text

from sase.ace.tui.model_alias_styles import OWNERSHIP_ACCENT, provider_model_text
from sase.core.time import format_local, get_timezone, parse_local
from sase.llm_provider.alias_history import (
    AliasHistoryGroup,
    AliasHistoryRun,
    AliasHistoryView,
)

from .alias_history_state import AliasHistoryEntryRequest, alias_history_run_key
from .models_panel_rendering_layout import pad_to_width, render_section_spacer

_TITLE_STYLE = "bold cyan"
_BUCKET_STYLE = "bold #FFD787"
_OWNERSHIP_STYLE = f"bold {OWNERSHIP_ACCENT}"

_STATUS_GLYPHS = {"done": "✓", "failed": "✗", "running": "▶"}
_STATUS_STYLES = {
    "done": "#87D787",
    "failed": "bold #D75F5F",
    "running": "bold #5FD7FF",
}
_HIDDEN_ROW_STYLE = "bold #FF5F87"
_RETRY_ROW_STYLE = "bold #FFAF00"
_TIME_STYLE = "#8787AF"
_IDENTITY_STYLE = "bold"
_PROJECT_STYLE = "#00D7AF"

_PROVENANCE_STYLES = {
    "direct": "bold #87D787",
    "default": "#87D7AF",
    "indirect": "#AF87FF",
    "unrecorded": "dim #9E9E9E",
}

_LABEL_STYLE = "bold #87D7FF"
_WORKSPACE_STYLE = "#5FD7FF"
_BEAD_STYLE = "bold #FFAF00"
_PATCH_STYLE = "#00D7AF"
_RETRY_FIELD_STYLE = "#FF8700"
_XPROMPT_GLYPHS = {"workflow": ("⌘", "bold #FFAF5F"), "swarm": ("❋", "bold #FF87D7")}
_XPROMPT_DEFAULT_GLYPH = ("▣", "bold #87FFAF")

_TIME_COLUMN_WIDTH = 9
_IDENTITY_COLUMN_WIDTH = 24
_PROJECT_COLUMN_WIDTH = 16


@dataclass(frozen=True, slots=True)
class _AliasHistoryRowSpec:
    """One row the modal should paint — a run, a group header, or a spacer."""

    option_id: str
    text: Text
    disabled: bool = False


def alias_history_title_text(
    entry: AliasHistoryEntryRequest, view: AliasHistoryView | None
) -> Text:
    """Render the title line: source label, ownership accent, and rollup counts."""
    text = Text(no_wrap=False)
    if entry.is_user_owned:
        text.append("▌ ", style=_OWNERSHIP_STYLE)
    text.append("History", style=_TITLE_STYLE)
    text.append(" · ", style="dim")
    label_style = (
        _OWNERSHIP_STYLE
        if entry.is_user_owned
        else _BUCKET_STYLE
        if not entry.is_single_alias
        else "bold"
    )
    text.append(entry.title_label, style=label_style)
    if entry.is_single_alias and entry.effective_model:
        text.append("  ")
        text.append_text(
            provider_model_text(
                entry.effective_provider,
                entry.effective_model,
                entry.effective_effort or "",
            )
        )
    if view is not None:
        text.append("\n")
        text.append_text(_rollup_text(view))
    return text


def _rollup_text(view: AliasHistoryView) -> Text:
    total = sum(group.total_count for group in view.groups)
    returned = sum(group.returned_count for group in view.groups)
    rollup = view.status_rollup
    text = Text(no_wrap=False)
    text.append(f"{total} recorded · {returned} shown  ", style="dim")
    text.append(f"✓{rollup.done} ", style=_STATUS_STYLES["done"])
    if rollup.failed:
        text.append(f"✗{rollup.failed} ", style=_STATUS_STYLES["failed"])
    if rollup.running:
        text.append(f"▶{rollup.running} ", style=_STATUS_STYLES["running"])
    return text


def _alias_history_group_header_text(group: AliasHistoryGroup) -> Text:
    """Render the disabled header separating one bucket member's runs."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"── @{group.alias} ", style=_TITLE_STYLE)
    text.append("─" * 3, style=_TITLE_STYLE)
    text.append("  ")
    text.append(_group_count_label(group), style="dim")
    return text


def _group_count_label(group: AliasHistoryGroup) -> str:
    rollup = group.status_rollup
    label = f"{group.total_count} recorded · {group.returned_count} shown"
    if rollup.failed or rollup.running:
        label += f" · ✗{rollup.failed} ▶{rollup.running}"
    return label


def _alias_history_row_text(run: AliasHistoryRun, *, now: float) -> Text:
    """Render one selectable run row."""
    text = Text(no_wrap=True, overflow="ellipsis")
    glyph = _STATUS_GLYPHS.get(run.rollup_status, "?")
    text.append(f"{glyph} ", style=_STATUS_STYLES.get(run.rollup_status, "dim"))
    if run.hidden:
        text.append("◌ ", style=_HIDDEN_ROW_STYLE)
    if run.retry_attempt:
        text.append(f"↻{run.retry_attempt} ", style=_RETRY_ROW_STYLE)
    text.append(
        pad_to_width(_relative_time(run, now=now), _TIME_COLUMN_WIDTH),
        style=_TIME_STYLE,
    )
    text.append("  ")
    identity = run.agent_name or run.workflow_name or "—"
    text.append(pad_to_width(identity, _IDENTITY_COLUMN_WIDTH), style=_IDENTITY_STYLE)
    text.append("  ")
    text.append(
        pad_to_width(run.project_name, _PROJECT_COLUMN_WIDTH), style=_PROJECT_STYLE
    )
    text.append("  ")
    text.append_text(
        provider_model_text(run.llm_provider, run.model, run.reasoning_effort or "")
    )
    text.append("  ")
    text.append(
        run.provenance.label,
        style=_PROVENANCE_STYLES.get(run.provenance.kind, "dim"),
    )
    return text


def build_alias_history_rows(
    view: AliasHistoryView, *, entry: AliasHistoryEntryRequest, now: float
) -> list[_AliasHistoryRowSpec]:
    """Build the flat, selectable row list for *view*.

    Grouped headers and a single spacer between groups appear only when more
    than one alias was requested (a bucket); a lone-alias request renders its
    runs directly. Headers, spacers, and per-group empty hints are always
    disabled and are never jump targets.
    """
    rows: list[_AliasHistoryRowSpec] = []
    multi = not entry.is_single_alias
    for index, group in enumerate(view.groups):
        if multi:
            if index:
                rows.append(
                    _AliasHistoryRowSpec(
                        f"__spacer__:{group.alias}",
                        render_section_spacer(),
                        disabled=True,
                    )
                )
            rows.append(
                _AliasHistoryRowSpec(
                    f"__group__:{group.alias}",
                    _alias_history_group_header_text(group),
                    disabled=True,
                )
            )
        if not group.runs:
            rows.append(
                _AliasHistoryRowSpec(
                    f"__empty__:{group.alias}",
                    Text(f"No recorded runs for @{group.alias}.", style="dim italic"),
                    disabled=True,
                )
            )
            continue
        for run in group.runs:
            rows.append(
                _AliasHistoryRowSpec(
                    alias_history_run_key(group.alias, run),
                    _alias_history_row_text(run, now=now),
                )
            )
    return rows


def alias_history_detail_text(
    run: AliasHistoryRun | None, *, entry: AliasHistoryEntryRequest
) -> Text:
    """Render the fixed detail strip for the highlighted run."""
    if run is None:
        return _alias_history_empty_text(entry)
    text = Text(no_wrap=False)
    text.append_text(_trail_line(run))
    text.append_text(_origin_line(run))
    if run.prompt_snippet:
        text.append("\n")
        text.append(run.prompt_snippet.strip(), style="italic #B0B0B0")
        text.append("\n")
    _append_field(text, "Project", run.project_name, style=_PROJECT_STYLE)
    if run.workspace_num is not None:
        _append_field(
            text, "Workspace", f"#{run.workspace_num}", style=_WORKSPACE_STYLE
        )
    if run.bead_id:
        _append_field(text, "Bead", run.bead_id, style=_BEAD_STYLE)
    if run.cl_name:
        _append_field(text, "Patch", run.cl_name, style=_PATCH_STYLE)
    start_duration = _start_duration_label(run)
    if start_duration:
        _append_field(text, "Start/Duration", start_duration, style=_TIME_STYLE)
    if run.retry_attempt:
        _append_field(
            text, "Retry", f"attempt #{run.retry_attempt}", style=_RETRY_FIELD_STYLE
        )
    if run.hidden:
        _append_field(
            text,
            "Hidden",
            "yes — press . to toggle hidden runs",
            style=_HIDDEN_ROW_STYLE,
        )
    if run.used_xprompts:
        text.append_text(_xprompts_line(run))
    return text


def _trail_line(run: AliasHistoryRun) -> Text:
    text = Text(no_wrap=False)
    text.append("Trail: ", style=_LABEL_STYLE)
    for alias in run.model_alias_trail:
        text.append(f"@{alias}", style="#AF87FF")
        text.append(" → ", style="dim")
    text.append_text(
        provider_model_text(run.llm_provider, run.model, run.reasoning_effort or "")
    )
    text.append("\n")
    return text


def _origin_line(run: AliasHistoryRun) -> Text:
    text = Text(no_wrap=False)
    text.append("Origin: ", style=_LABEL_STYLE)
    provenance = run.provenance
    if provenance.kind == "direct":
        text.append("explicit %model directive", style=_PROVENANCE_STYLES["direct"])
    elif provenance.kind == "default":
        text.append("configured default model", style=_PROVENANCE_STYLES["default"])
    elif provenance.kind == "indirect":
        via = provenance.via_alias
        label = f"via @{via}" if via else "via an earlier alias hop"
        text.append(label, style=_PROVENANCE_STYLES["indirect"])
    else:
        text.append(
            "unrecorded — no alias origin was captured for this run",
            style=_PROVENANCE_STYLES["unrecorded"],
        )
    text.append("\n")
    return text


def _append_field(text: Text, label: str, value: str, *, style: str) -> None:
    text.append(f"{label}: ", style=_LABEL_STYLE)
    text.append(f"{value}\n", style=style)


def _xprompts_line(run: AliasHistoryRun) -> Text:
    text = Text(no_wrap=False)
    text.append("Xprompts: ", style=_LABEL_STYLE)
    for index, used in enumerate(run.used_xprompts):
        if index:
            text.append("  ")
        glyph, style = _XPROMPT_GLYPHS.get(used.kind, _XPROMPT_DEFAULT_GLYPH)
        text.append(f"{glyph} ", style=style)
        text.append(f"#{used.name}", style=style)
    text.append("\n")
    return text


def _alias_history_empty_text(entry: AliasHistoryEntryRequest) -> Text:
    """Render the detail-strip explanation when a group has no selectable run."""
    text = Text(no_wrap=False)
    names = ", ".join(f"@{alias}" for alias in entry.aliases)
    text.append(f"No recorded runs for {names}.\n", style="italic #B0B0B0")
    text.append(
        "Provenance-aware alias history is only recorded for runs launched "
        "after this feature shipped — earlier runs will not appear here.",
        style="dim #9E9E9E",
    )
    return text


def alias_history_footer_markup(*, include_hidden: bool, has_more: bool) -> str:
    """Render the modal's own context footer, one line per action group."""
    hidden_state = "showing" if include_hidden else "excluded"
    more_hint = "  [dim]more available[/dim]" if has_more else ""
    return (
        "[green]enter[/green]=Prompt  "
        "[green]y[/green]=Copy  "
        "[green]ctrl+j[/green]=Load more  "
        "[green]ctrl+k[/green]=Unload  "
        "[green]r[/green]=Refresh  "
        f"[green].[/green]=Hidden ({hidden_state})\n"
        "[dim]j/k[/dim]=Navigate  [dim]'[/dim]=Jump  "
        f"[dim]esc[/dim]=Close{more_hint}"
    )


def _run_epoch(run: AliasHistoryRun) -> float | None:
    """Return *run*'s start time as an epoch, or ``None`` when unparseable."""
    started = parse_local(run.started_at)
    if started is None:
        try:
            naive = datetime.strptime(run.timestamp, "%Y%m%d%H%M%S")
        except ValueError:
            return None
        started = naive.replace(tzinfo=get_timezone())
    return started.timestamp()


def _relative_time(run: AliasHistoryRun, *, now: float) -> str:
    epoch = _run_epoch(run)
    if epoch is None:
        return "—"
    delta = max(0.0, now - epoch)
    if delta < 60:
        return "just now"
    minutes = int(delta // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(delta // 3600)
    if hours < 24:
        return f"{hours}h ago"
    days = int(delta // 86400)
    if days < 7:
        return f"{days}d ago"
    return format_local(epoch, "%b %d %H:%M")


def _start_duration_label(run: AliasHistoryRun) -> str | None:
    epoch = _run_epoch(run)
    if epoch is None:
        return None
    started = format_local(epoch, "%Y-%m-%d %H:%M:%S")
    if run.duration_seconds is None:
        return started
    return f"{started} · {_format_run_duration(run.duration_seconds)}"


def _format_run_duration(seconds: float) -> str:
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


__all__ = [
    "alias_history_detail_text",
    "alias_history_footer_markup",
    "alias_history_title_text",
    "build_alias_history_rows",
]
