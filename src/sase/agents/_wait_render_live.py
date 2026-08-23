"""TTY live panel and settle summary for ``sase agent wait``."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from types import TracebackType

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS
from sase.agent.wait_watch import WaitSettlement, WaitTargetState, WaitTick
from sase.agents._wait_live_rows import (
    WaitLiveRow,
    build_wait_live_rows,
    format_elapsed_clock,
    terminal_blocker_warnings,
)
from sase.agents._wait_render_plain import format_duration
from sase.agents.status_style import agent_status_text
from sase.core.agent_scan_wire import AgentArtifactScanWire

_BORDER_STYLE = "cyan"
_GLYPH_STYLES = {
    "Stopped": "yellow",
    "Starting": "cyan",
    "Running": "green",
    "Queued": "#5F87FF",
    "Waiting": "yellow",
    "Failed": "red",
    "Done": "green",
}


def should_render_wait_live(
    *,
    as_json: bool,
    quiet: bool,
    use_live: bool | None = None,
    stdout_isatty: bool | None = None,
) -> bool:
    """Return whether the refreshing TTY panel should be used."""

    if as_json or quiet:
        return False
    if use_live is not None:
        return use_live
    if stdout_isatty is not None:
        return stdout_isatty
    return sys.stdout.isatty()


def _render_wait_live_panel(
    tick: WaitTick,
    snapshot: AgentArtifactScanWire,
) -> Panel:
    """Return the in-flight wait panel for *tick*."""

    rows = build_wait_live_rows(
        tick.target_states, snapshot, elapsed_seconds=tick.elapsed_seconds
    )
    warnings = terminal_blocker_warnings(tick.target_states, snapshot)
    pending = sum(1 for row in rows if row.unfinished)
    done = sum(1 for row in rows if row.succeeded)
    failed = sum(1 for row in rows if row.failed)
    noun = "agent" if len(tick.target_states) == 1 else "agents"
    title = (
        f"Waiting on {len(tick.target_states)} {noun} · "
        f"{format_elapsed_clock(tick.elapsed_seconds)} elapsed"
    )
    subtitle = f"{pending} pending · {done} done · {failed} failed"
    body: list[RenderableType] = [_live_table(rows)]
    for warning in warnings:
        body.append(Text(f"⚠ {warning}", style="yellow"))
    return Panel(
        Group(*body),
        title=title,
        subtitle=subtitle,
        title_align="left",
        subtitle_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def render_wait_settle_panel(
    settlement: WaitSettlement,
    snapshot: AgentArtifactScanWire,
    *,
    exit_code: int,
) -> Panel:
    """Return the post-teardown settle summary for *settlement*."""

    rows = build_wait_live_rows(
        settlement.target_states,
        snapshot,
        elapsed_seconds=settlement.elapsed_seconds,
    )
    # Summary keeps requested target order rather than unfinished-first.
    ordered = _settle_row_order(settlement.target_states, rows)
    noun = "agent" if len(settlement.target_states) == 1 else "agents"
    title = (
        f"Waited {format_duration(settlement.elapsed_seconds)} · "
        f"{len(settlement.target_states)} {noun}"
    )
    succeeded = sum(1 for row in ordered if row.succeeded)
    failed = sum(1 for row in ordered if row.failed)
    blocked = sum(1 for row in ordered if row.blocked)
    subtitle = (
        f"{succeeded} succeeded · {failed} failed · {blocked} blocked"
        f" → exit {exit_code}"
    )
    return Panel(
        _settle_body(ordered),
        title=title,
        subtitle=subtitle,
        title_align="left",
        subtitle_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


class WaitLiveDisplay:
    """Refreshing ``rich.Live`` panel torn down in ``finally``."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None

    def __enter__(self) -> WaitLiveDisplay:
        self._live = Live(
            Text(""),
            console=self._console,
            transient=True,
            refresh_per_second=8,
        )
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        live = self._live
        self._live = None
        if live is not None:
            live.__exit__(exc_type, exc, tb)

    def update(self, tick: WaitTick, snapshot: AgentArtifactScanWire) -> None:
        if self._live is None:
            return
        self._live.update(_render_wait_live_panel(tick, snapshot))


def _live_table(rows: Sequence[WaitLiveRow]) -> Table:
    table = Table(
        box=None,
        show_header=False,
        pad_edge=False,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("glyph", no_wrap=True)
    table.add_column("name", style="bold", no_wrap=True, overflow="ellipsis")
    table.add_column("project", no_wrap=True, overflow="ellipsis")
    table.add_column("ws", justify="right", no_wrap=True)
    table.add_column("model", no_wrap=True, overflow="ellipsis")
    table.add_column("status", no_wrap=True)
    table.add_column("duration", justify="right", no_wrap=True)
    table.add_column("why", overflow="ellipsis", ratio=1)
    for row in rows:
        table.add_row(
            _glyph_text(row),
            row.name,
            row.project,
            row.workspace,
            row.model,
            _status_text(row),
            row.duration,
            row.why or "",
        )
    return table


def _settle_body(rows: Sequence[WaitLiveRow]) -> Group:
    table = Table(
        box=None,
        show_header=False,
        pad_edge=False,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("glyph", no_wrap=True)
    table.add_column("name", style="bold", no_wrap=True, overflow="ellipsis")
    table.add_column("status", no_wrap=True)
    table.add_column("duration", justify="right", no_wrap=True)
    table.add_column("where", overflow="fold", ratio=1)
    extra: list[RenderableType] = []
    for row in rows:
        table.add_row(
            _glyph_text(row),
            row.name,
            _status_text(row),
            row.duration,
            _where_text(row),
        )
        extra.extend(_settle_detail_lines(row))
    if extra:
        return Group(table, *extra)
    return Group(table)


def _settle_detail_lines(row: WaitLiveRow) -> list[Text]:
    lines: list[Text] = []
    detail = row.error or row.blocked_reason
    if detail:
        style = "red" if row.failed else "yellow"
        lines.append(Text(f"    {detail}", style=style))
    pointers: list[str] = []
    if row.unblock_command:
        pointers.append(row.unblock_command)
    pointers.extend(row.inspect_commands)
    if pointers:
        lines.append(Text("    " + " · ".join(pointers), style="dim"))
    return lines


def _settle_row_order(
    target_states: Sequence[WaitTargetState],
    rows: Sequence[WaitLiveRow],
) -> tuple[WaitLiveRow, ...]:
    by_name = {row.name: row for row in rows}
    ordered: list[WaitLiveRow] = []
    seen: set[str] = set()
    for state in target_states:
        names: list[str] = []
        if state.members and len(state.members) > 1:
            names.extend(member.name for member in state.members)
        else:
            names.append(state.target.name)
        for name in names:
            row = by_name.get(name)
            if row is not None and name not in seen:
                seen.add(name)
                ordered.append(row)
    for row in rows:
        if row.name not in seen:
            ordered.append(row)
    return tuple(ordered)


def _glyph_text(row: WaitLiveRow) -> Text:
    glyph = row.glyph or AGENT_STATUS_BUCKET_GLYPHS.get("Running", "▶")
    return Text(glyph, style=_GLYPH_STYLES.get(row.status_bucket, ""))


def _status_text(row: WaitLiveRow) -> Text:
    return agent_status_text(
        row.status, monitor=row.monitor, monitor_state=row.monitor_state
    )


def _where_text(row: WaitLiveRow) -> str:
    workspace = row.workspace
    if workspace != "-":
        workspace = f"ws{workspace}"
    return f"{row.project} · {workspace}"


__all__ = [
    "WaitLiveDisplay",
    "render_wait_settle_panel",
    "should_render_wait_live",
]
