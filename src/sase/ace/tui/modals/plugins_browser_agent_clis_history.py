"""Pure renderables for agent-CLI update history in the Updates pane."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent_clis.history import AgentCliUpdateRun, AgentCliUpdateRunEntry
from sase.agent_clis.models import AgentCliStatus, UpdateResultStatus, UpdateTrigger

_ACCENT = "#87D7FF"
_BORDER = "#5F5F87"
_SUCCESS = "#00D700"
_FAILURE = "#FF5F5F"
_TRIGGER = "#AF87FF"
_FAILURE_REASON_MAX_CELLS = 52

_GLYPHS: dict[UpdateResultStatus, tuple[str, str]] = {
    UpdateResultStatus.UPDATED: ("▲", f"bold {_SUCCESS}"),
    UpdateResultStatus.FAILED: ("✖", f"bold {_FAILURE}"),
    UpdateResultStatus.ALREADY_CURRENT: ("·", "dim"),
    UpdateResultStatus.SKIPPED: ("○", "dim"),
}
_TRIGGER_BADGES: dict[UpdateTrigger, str] = {
    UpdateTrigger.COMPREHENSIVE: ",U",
    UpdateTrigger.ADMIN_CENTER: "A",
    UpdateTrigger.CLI: "CLI",
    UpdateTrigger.UNKNOWN: "—",
}


def build_agent_cli_history_panel(
    status: AgentCliStatus | None,
    runs: Sequence[AgentCliUpdateRun],
    *,
    enabled: bool,
    error: str | None,
    all_clis: bool,
    now: float,
    max_rows: int,
    colors: Mapping[str, str],
) -> RenderableType:
    """Build the selected CLI's history panel from already-loaded state."""
    if not enabled or status is None:
        return Text()

    title = "Update history · all agent CLIs" if all_clis else "Update history"
    title_text = Text(title, style=f"bold {colors.get(status.name, _ACCENT)}")
    toggle_hint = "H this CLI" if all_clis else "H all CLIs"

    if error is not None:
        body = Text("Could not read update history:\n", style=_FAILURE)
        body.append(error, style=_FAILURE)
        return _panel(body, title=title_text, subtitle=toggle_hint)

    if not runs:
        return _panel(
            _empty_history_text(),
            title=title_text,
            subtitle=toggle_hint,
        )

    if all_clis:
        visible = tuple(runs) if max_rows == 0 else tuple(runs[:max_rows])
        return _panel(
            _all_clis_body(visible, now=now, colors=colors),
            title=title_text,
            subtitle=_subtitle(
                shown=len(visible),
                total=len(runs),
                max_rows=max_rows,
                toggle_hint=toggle_hint,
            ),
        )

    eligible = tuple(
        (run, entry)
        for run in runs
        for entry in run.executed_entries
        if entry.name == status.name
    )
    if not eligible:
        other_run_count = sum(
            any(entry.name != status.name for entry in run.entries) for run in runs
        )
        body = Text(f"No recorded updates for {status.display_name}.")
        if other_run_count:
            body.append("\n")
            body.append(
                f"{other_run_count} {_plural_run(other_run_count)} recorded for "
                "other CLIs — press H to see them.",
                style="dim",
            )
        return _panel(body, title=title_text, subtitle=toggle_hint)

    visible_entries = eligible if max_rows == 0 else eligible[:max_rows]
    return _panel(
        _per_cli_body(visible_entries, now=now),
        title=title_text,
        subtitle=_subtitle(
            shown=len(visible_entries),
            total=len(eligible),
            max_rows=max_rows,
            toggle_hint=toggle_hint,
        ),
    )


def _panel(
    body: RenderableType,
    *,
    title: Text,
    subtitle: str,
) -> Panel:
    return Panel(
        body,
        title=title,
        subtitle=Text(subtitle, style="dim"),
        border_style=_BORDER,
        expand=True,
    )


def _empty_history_text() -> Text:
    body = Text("No sase-managed agent CLI updates recorded yet.")
    body.append(
        "\nPress A to update agent CLIs, or ,U to update everything.",
        style="dim",
    )
    return body


def _per_cli_body(
    rows: Sequence[tuple[AgentCliUpdateRun, AgentCliUpdateRunEntry]],
    *,
    now: float,
) -> Table:
    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    for run, entry in rows:
        glyph, glyph_style = _GLYPHS[entry.status]
        table.add_row(
            Text(glyph, style=glyph_style),
            _version_text(entry),
            Text(_relative_time(run.epoch, now=now), style="dim"),
            Text(_trigger_badge(run.trigger), style=f"bold {_TRIGGER}"),
            Text(_elapsed(entry.elapsed_seconds), style="dim"),
            _failure_reason(entry),
        )
    return table


def _all_clis_body(
    runs: Sequence[AgentCliUpdateRun],
    *,
    now: float,
    colors: Mapping[str, str],
) -> Group:
    lines: list[Text] = []
    for index, run in enumerate(runs):
        if index:
            lines.append(Text())
        header = Text(_relative_time(run.epoch, now=now), style="dim")
        header.append(" · ", style="dim")
        header.append(_trigger_badge(run.trigger), style=f"bold {_TRIGGER}")
        header.append(" · ", style="dim")
        header.append(_elapsed(run.elapsed_seconds), style="dim")
        lines.append(header)
        for entry in run.executed_entries:
            lines.append(_all_clis_entry(entry, colors=colors))
        summary = _nonexecuted_summary(run)
        if summary is not None:
            lines.append(summary)
    return Group(*lines)


def _all_clis_entry(
    entry: AgentCliUpdateRunEntry,
    *,
    colors: Mapping[str, str],
) -> Text:
    glyph, glyph_style = _GLYPHS[entry.status]
    line = Text("  ")
    line.append(glyph, style=glyph_style)
    line.append(" ")
    line.append(f"{entry.display_name:<14}", style=colors.get(entry.name, _ACCENT))
    line.append_text(_version_text(entry))
    reason = _failure_reason(entry)
    if reason.plain:
        line.append("  ")
        line.append_text(reason)
    line.no_wrap = True
    line.overflow = "ellipsis"
    return line


def _nonexecuted_summary(run: AgentCliUpdateRun) -> Text | None:
    current = sum(
        entry.status is UpdateResultStatus.ALREADY_CURRENT
        for entry in run.entries
        if entry.command is None
    )
    skipped = sum(
        entry.status is UpdateResultStatus.SKIPPED
        for entry in run.entries
        if entry.command is None
    )
    if not current and not skipped:
        return None
    line = Text("  ", style="dim")
    if current:
        line.append(f"· {current} already current", style="dim")
    if current and skipped:
        line.append(" · ", style="dim")
    if skipped:
        line.append(f"○ {skipped} skipped", style="dim")
    return line


def _version_text(entry: AgentCliUpdateRunEntry) -> Text:
    old = entry.old_version or entry.new_version or "unknown"
    text = Text(old, style="dim")
    if entry.status is UpdateResultStatus.UPDATED:
        text.append(" → ", style="dim")
        text.append(entry.new_version or "unknown", style=f"bold {_SUCCESS}")
    return text


def _failure_reason(entry: AgentCliUpdateRunEntry) -> Text:
    if entry.status is not UpdateResultStatus.FAILED:
        return Text()
    reason = Text(
        entry.reason or entry.output_tail or "update failed",
        style=_FAILURE,
        no_wrap=True,
        overflow="ellipsis",
    )
    reason.truncate(_FAILURE_REASON_MAX_CELLS, overflow="ellipsis")
    return reason


def _relative_time(epoch: float, *, now: float) -> str:
    age = max(0, int(now - epoch))
    if epoch >= now:
        return "just now"
    if age < 60:
        return f"{age}s ago"
    minutes = age // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    return datetime.fromtimestamp(epoch).strftime("%b %d %H:%M")


def _trigger_badge(trigger: UpdateTrigger) -> str:
    return _TRIGGER_BADGES.get(trigger, "—")


def _elapsed(seconds: float) -> str:
    return f"{max(0.0, seconds):.1f}s"


def _subtitle(
    *,
    shown: int,
    total: int,
    max_rows: int,
    toggle_hint: str,
) -> str:
    if max_rows == 0:
        return toggle_hint
    return f"{shown} of {total} runs · {toggle_hint}"


def _plural_run(count: int) -> str:
    return "run" if count == 1 else "runs"


__all__ = ["build_agent_cli_history_panel"]
