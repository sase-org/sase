"""Human and JSON rendering for ``sase axe status``."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from typing import TextIO

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .state import (
    LumberjackMetrics,
    format_lumberjack_chop_load,
    format_no_op_ratio,
    read_lumberjack_metrics,
)
from .status_models import (
    AxeLumberjackState,
    AxeLumberjackStatus,
    AxeProcessObservation,
    AxeStatusHealth,
    AxeStatusSnapshot,
    AxeStatusState,
)


_STATE_STYLES: dict[AxeStatusState, str] = {
    "running": "bold green",
    "maintenance": "bold yellow",
    "stopped": "bold cyan",
    "not_started": "dim cyan",
    "down": "bold red",
    "degraded": "bold red",
    "error": "bold red",
}
_HEALTH_STYLES: dict[AxeStatusHealth, str] = {
    "healthy": "bold green",
    "unhealthy": "bold red",
    "error": "bold red",
}
_LUMBERJACK_STYLES: dict[AxeLumberjackState, str] = {
    "running": "green",
    "not_reporting": "yellow",
    "stale_process": "red",
    "stale_heartbeat": "red",
    "error": "red",
    "orphaned": "red",
}
_NARROW_WIDTH = 100


def render_axe_status_human(
    snapshot: AxeStatusSnapshot,
    *,
    console: Console | None = None,
) -> None:
    """Render one operator-friendly AXE status dashboard."""
    target = console or Console()
    renderables: list[RenderableType] = [
        _summary_panel(snapshot),
        _lumberjack_table(snapshot.lumberjacks, width=target.width),
    ]
    attention = _attention_panel(snapshot)
    if attention is not None:
        renderables.append(attention)
    target.print(Group(*renderables))


def render_axe_status_json(
    snapshot: AxeStatusSnapshot,
    *,
    stream: TextIO | None = None,
) -> None:
    """Write the exact schema-version-1 snapshot as deterministic plain JSON."""
    target = stream or sys.stdout
    json.dump(
        snapshot.to_wire(),
        target,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    target.write("\n")


def _summary_panel(snapshot: AxeStatusSnapshot) -> Panel:
    summary = Table.grid(padding=(0, 2), expand=True)
    summary.add_column(style="bold", no_wrap=True)
    summary.add_column(overflow="fold")
    summary.add_row("State", _badge(snapshot.state, _STATE_STYLES[snapshot.state]))
    summary.add_row(
        "Health",
        _badge(snapshot.health, _HEALTH_STYLES[snapshot.health]),
    )
    summary.add_row("Summary", Text(snapshot.summary, overflow="fold"))
    summary.add_row("Generated", Text(snapshot.generated_at, overflow="fold"))
    summary.add_row("Desired", Text(_desired_state_summary(snapshot), overflow="fold"))
    summary.add_row(
        "Orchestrator",
        Text(_orchestrator_summary(snapshot), overflow="fold"),
    )
    summary.add_row(
        "Maintenance",
        Text(_maintenance_summary(snapshot), overflow="fold"),
    )
    summary.add_row(
        "Runners",
        Text(
            "hooks "
            f"{snapshot.hook_runners.current}/{snapshot.hook_runners.maximum}"
            " · agents "
            f"{snapshot.agent_runners.current}/{snapshot.agent_runners.maximum}",
            overflow="fold",
        ),
    )
    summary.add_row(
        "Latest event",
        Text(_lifecycle_event_summary(snapshot), overflow="fold"),
    )
    summary.add_row(
        "Chop load",
        Text(_chop_load_summary(snapshot.lumberjacks), overflow="fold"),
    )
    return Panel(
        summary,
        title="AXE Status",
        border_style=_STATE_STYLES[snapshot.state],
    )


def _badge(value: str, style: str) -> Text:
    return Text(f"[{value.replace('_', ' ').upper()}]", style=style)


def _desired_state_summary(snapshot: AxeStatusSnapshot) -> str:
    desired = snapshot.desired_state
    if desired is None:
        return "not recorded"
    return f"{desired.state} · source={desired.source} · at {desired.timestamp}"


def _orchestrator_summary(snapshot: AxeStatusSnapshot) -> str:
    orchestrator = snapshot.orchestrator
    live_pids = ", ".join(str(pid) for pid in orchestrator.live_pids) or "-"
    return (
        f"{orchestrator.state} · coherence={orchestrator.coherence}"
        f" · live PIDs={live_pids}"
        f" · lock={'held' if orchestrator.lifecycle_lock_held else 'not held'}\n"
        f"lock holder={_process_summary(orchestrator.lock_holder)}"
        f" · PID file={_process_summary(orchestrator.orchestrator_pid_file)}"
        f" · legacy PID={_process_summary(orchestrator.legacy_pid_file)}"
    )


def _process_summary(observation: AxeProcessObservation) -> str:
    if observation.pid is None:
        return "-"
    return f"{observation.pid} ({'live' if observation.live else 'dead'})"


def _maintenance_summary(snapshot: AxeStatusSnapshot) -> str:
    maintenance = snapshot.maintenance
    if maintenance is None:
        return "inactive"
    return (
        f"{maintenance.reason} · owner PID={maintenance.owner_pid}"
        f" · age={_format_age(maintenance.age_seconds)}"
        f" · since {maintenance.started_at}"
    )


def _lifecycle_event_summary(snapshot: AxeStatusSnapshot) -> str:
    event = snapshot.latest_lifecycle_event
    if event is None:
        return "-"
    parts = [
        event.event,
        f"outcome={event.outcome}",
        f"success={'yes' if event.success else 'no'}",
        f"source={event.source}",
        f"at {event.timestamp}",
        f"age={_format_age(event.age_seconds)}",
    ]
    if event.orchestrator_pid is not None:
        parts.append(f"PID={event.orchestrator_pid}")
    if event.reason is not None:
        parts.append(f"reason={event.reason}")
    return " · ".join(parts)


def _lumberjack_table(
    lumberjacks: Iterable[AxeLumberjackStatus],
    *,
    width: int,
) -> Table:
    rows = sorted(lumberjacks, key=lambda lumberjack: lumberjack.name)
    if width < _NARROW_WIDTH:
        return _narrow_lumberjack_table(rows)
    return _wide_lumberjack_table(rows)


def _wide_lumberjack_table(rows: list[AxeLumberjackStatus]) -> Table:
    table = Table(
        title="Lumberjacks",
        show_header=True,
        header_style="bold",
        show_lines=True,
        expand=True,
    )
    table.add_column("Name", overflow="fold")
    table.add_column("State", overflow="fold")
    table.add_column("PID", overflow="fold")
    table.add_column("Heartbeat", overflow="fold")
    table.add_column("Cycles", overflow="fold")
    table.add_column("Errors", overflow="fold")
    table.add_column("Chops", overflow="fold")
    table.add_column("Load", overflow="fold")
    if not rows:
        table.add_row(Text("No lumberjacks observed.", style="dim"), *[""] * 7)
        return table

    for row in rows:
        name = Text(row.name)
        name.append(
            "\n"
            f"configured={_yes_no(row.configured)}"
            f" · interval={_format_duration(row.interval_seconds)}",
            style="dim",
        )
        state = Text(
            row.state.replace("_", " "),
            style=_LUMBERJACK_STYLES[row.state],
        )
        state.append(
            f"\nstale threshold={_format_duration(row.stale_threshold_seconds)}",
            style="dim",
        )
        pid = Text(
            f"{_placeholder(row.recorded_pid)}"
            f" (live={_yes_no_unknown(row.process_live)})"
        )
        pid.append(
            f"\nreported={_placeholder(row.reported_state)}",
            style="dim",
        )
        heartbeat = Text(_format_age(row.heartbeat_age_seconds))
        heartbeat.append(
            f"\nat {_placeholder(row.heartbeat_at)}",
            style="dim",
        )
        cycles = Text(str(row.cycles_run))
        cycles.append(
            "\n"
            f"started={_placeholder(row.started_at)}"
            f" ({_format_age(row.start_age_seconds)})"
            f"\nuptime={_format_duration(row.uptime_seconds)}",
            style="dim",
        )
        chops = Text("\n".join(row.configured_chops) or "-", overflow="fold")
        load = Text(_lumberjack_load_text(row.name), overflow="fold")
        table.add_row(
            name,
            state,
            pid,
            heartbeat,
            cycles,
            str(row.errors_encountered),
            chops,
            load,
        )
    return table


def _narrow_lumberjack_table(rows: list[AxeLumberjackStatus]) -> Table:
    table = Table(
        title="Lumberjacks",
        show_header=True,
        header_style="bold",
        show_lines=True,
        expand=True,
    )
    table.add_column("Name", ratio=1, overflow="fold")
    table.add_column("Details", ratio=4, overflow="fold")
    if not rows:
        table.add_row(
            Text("-", style="dim"), Text("No lumberjacks observed.", style="dim")
        )
        return table

    for row in rows:
        details = Text()
        details.append(
            f"state={row.state}",
            style=_LUMBERJACK_STYLES[row.state],
        )
        details.append(
            "\n"
            f"configured={_yes_no(row.configured)}"
            f" · interval={_format_duration(row.interval_seconds)}"
            f" · stale threshold={_format_duration(row.stale_threshold_seconds)}"
            "\n"
            f"PID={_placeholder(row.recorded_pid)}"
            f" · live={_yes_no_unknown(row.process_live)}"
            f" · reported={_placeholder(row.reported_state)}"
            "\n"
            f"heartbeat={_format_age(row.heartbeat_age_seconds)}"
            f" · at {_placeholder(row.heartbeat_at)}"
            "\n"
            f"cycles={row.cycles_run}"
            f" · errors={row.errors_encountered}"
            f" · uptime={_format_duration(row.uptime_seconds)}"
            "\n"
            f"started={_placeholder(row.started_at)}"
            f" · age={_format_age(row.start_age_seconds)}"
            "\n"
            f"chops={', '.join(row.configured_chops) or '-'}"
            "\n"
            f"load={_lumberjack_load_text(row.name).replace(chr(10), ' · ')}"
        )
        table.add_row(Text(row.name, overflow="fold"), details)
    return table


def _attention_panel(snapshot: AxeStatusSnapshot) -> Panel | None:
    if snapshot.collection_error is None and not snapshot.issues:
        return None

    body = Text()
    if snapshot.collection_error is not None:
        body.append("Collection error", style="bold red")
        body.append(
            f" [{snapshot.collection_error.code}]: "
            f"{snapshot.collection_error.message}\n"
        )

    for index, issue in enumerate(snapshot.issues, start=1):
        style = "red" if issue.severity == "error" else "yellow"
        body.append(f"{index}. [{issue.severity.upper()}] ", style=f"bold {style}")
        body.append(issue.summary)
        if issue.subject is not None:
            body.append(f" ({issue.subject})", style="dim")
        body.append("\n")

    commands = _deduplicated_commands(snapshot)
    if commands:
        body.append("Next steps\n", style="bold")
        for command in commands:
            body.append("  $ ", style="dim")
            body.append(command, style="bold cyan")
            body.append("\n")

    if body.plain.endswith("\n"):
        body.rstrip()
    has_error = snapshot.collection_error is not None or any(
        issue.severity == "error" for issue in snapshot.issues
    )
    return Panel(
        body,
        title="Attention",
        border_style="red" if has_error else "yellow",
    )


def _deduplicated_commands(snapshot: AxeStatusSnapshot) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for issue in snapshot.issues:
        command = issue.suggested_command
        if command is None or command in seen:
            continue
        seen.add(command)
        commands.append(command)
    if snapshot.health != "healthy" and not commands:
        commands.append("sase doctor --deep")
    return commands


def _format_age(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    return f"{_format_duration(seconds)} ago"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, remaining = divmod(seconds, 60)
        return f"{minutes}m {remaining:02d}s"
    if seconds < 86400:
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes:02d}m"
    days, remainder = divmod(seconds, 86400)
    hours = remainder // 3600
    return f"{days}d {hours:02d}h"


def _lumberjack_metrics(name: str) -> LumberjackMetrics | None:
    try:
        return read_lumberjack_metrics(name)
    except OSError:
        return None


def _lumberjack_load_text(name: str) -> str:
    return format_lumberjack_chop_load(_lumberjack_metrics(name))


def _chop_load_summary(lumberjacks: Iterable[AxeLumberjackStatus]) -> str:
    total_rate = 0.0
    total_spawned = 0
    total_no_op = 0
    last_spawns = 0
    last_skipped = 0
    found = False
    for row in lumberjacks:
        metrics = _lumberjack_metrics(row.name)
        if metrics is None:
            continue
        found = True
        total_rate += metrics.spawn_rate_per_minute
        total_spawned += metrics.chops_spawned
        total_no_op += metrics.chops_no_op
        last_spawns += metrics.last_tick_spawns
        last_skipped += metrics.last_tick_skipped
    if not found:
        return "no lumberjack metrics yet"
    fake = LumberjackMetrics(
        chops_spawned=total_spawned,
        chops_no_op=total_no_op,
        no_op_ratio=(total_no_op / total_spawned) if total_spawned else 0.0,
    )
    return (
        f"{total_rate:.1f} spawns/min · no-op {format_no_op_ratio(fake)}"
        f" · last tick {last_spawns} spawned / {last_skipped} skipped"
    )


def _placeholder(value: object | None) -> str:
    return "-" if value is None else str(value)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "-"
    return _yes_no(value)


__all__ = ["render_axe_status_human", "render_axe_status_json"]
