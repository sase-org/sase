"""Pure Perf-view presentation for the Statistics pane."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.time import format_local
from sase.telemetry.render import (
    categorical_color,
    empty_state,
    format_bytes,
    format_duration,
    format_percentage,
    format_tokens,
    render_stat_tile,
    status_color,
)

from .statistics_pane_data import StatisticsViewData

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"
_MUTED = "#808080"
_PERF_GROUP_LABELS: dict[str, str] = {
    "subsystem": "By Subsystem",
    "provider": "By Provider",
    "workflow": "By Workflow",
}
_LOG_SOURCE_ORDER: tuple[str, ...] = (
    "startup",
    "stalls",
    "launch_timing",
    "agent_loads",
    "git_ops",
    "external_tools",
)
_TELEMETRY_TILE_KEYS = frozenset({"agent_p95", "llm_p95"})
_DISABLED_TELEMETRY_MESSAGE = "Telemetry is disabled (telemetry.enabled)."


class StatisticsPerfRenderingMixin:
    """Render Perf metrics from the already-loaded immutable snapshot."""

    _perf_stacked: bool
    size: Any

    @staticmethod
    def _share_bar(value: float, maximum: float, *, width: int = 14) -> Text:
        raise NotImplementedError

    def _effective_key(self, action: str) -> str:
        raise NotImplementedError

    def _perf_renderable(self, result: StatisticsViewData) -> Any:
        perf = result.perf
        if perf is None:
            return self._perf_unavailable_renderable()
        available_width = max(76, int(self.size.width or 120) - 2)
        if self._perf_stacked:
            middle: Any = Group(
                self._perf_startup_panel(perf, width=available_width),
                self._perf_stalls_panel(perf, width=available_width),
            )
        else:
            section_width = max(36, (available_width - 2) // 2)
            middle = Columns(
                (
                    self._perf_startup_panel(perf, width=section_width),
                    self._perf_stalls_panel(perf, width=section_width),
                ),
                equal=True,
                expand=True,
                width=section_width,
            )
        return Group(
            middle,
            self._perf_latency_panel(perf, width=available_width),
            self._perf_coverage_panel(perf, width=available_width),
        )

    def _perf_hero_tiles(
        self, result: StatisticsViewData, *, width: int
    ) -> tuple[Any, ...]:
        perf = result.perf
        if perf is None:
            return tuple(
                self._perf_empty_tile("Unavailable", width=width) for _ in range(5)
            )
        return tuple(
            self._perf_stat_tile(tile, perf, width=width) for tile in perf.tiles
        )

    def _perf_stat_tile(self, tile: Any, perf: Any, *, width: int) -> Panel:
        telemetry = perf.coverage.telemetry
        if tile.key in _TELEMETRY_TILE_KEYS and not telemetry.enabled:
            return self._perf_empty_tile(
                tile.caption,
                width=width,
                message=_DISABLED_TELEMETRY_MESSAGE,
            )
        recording_started_at = (
            telemetry.earliest_sample_ts if tile.key in _TELEMETRY_TILE_KEYS else None
        )
        return render_stat_tile(
            self._perf_tile_value(tile),
            caption=tile.caption,
            width=width,
            height=6,
            key=tile.key,
            delta=None if tile.delta_ratio is None else tile.delta_ratio * 100.0,
            lower_is_better=tile.lower_is_better,
            sparkline=tile.sparkline or None,
            status=tile.status,
            recording_started_at=recording_started_at,
        )

    @staticmethod
    def _perf_tile_value(tile: Any) -> float | str | None:
        if not tile.available or tile.value is None:
            return None
        if tile.key == "stalls":
            primary = str(int(tile.value))
        elif tile.key == "launch":
            primary = format_duration(tile.value / 1000.0)
        else:
            primary = format_duration(tile.value)
        if tile.detail and tile.key != "startup":
            detail = tile.detail
            if tile.key == "launch":
                detail = detail.replace(" slow stages", " slow")
            return f"{primary}\n{detail}"
        return primary

    def _perf_startup_panel(self, perf: Any, *, width: int) -> Panel:
        startup = perf.startup
        title = "Startup breakdown"
        if not startup.available:
            return self._perf_section_empty(
                title,
                width=width,
                source="startup",
                coverage=perf.coverage,
                border_style=_CYAN,
            )
        table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
        table.add_column("Stage", style="bold", ratio=1)
        table.add_column("p50", justify="right", style=_CYAN)
        table.add_column("p95", justify="right", style=_CYAN)
        table.add_column("max", justify="right")
        for row in startup.stages:
            table.add_row(
                row.label,
                self._perf_duration(row.p50),
                self._perf_duration(row.p95),
                self._perf_duration(row.max),
            )
        footer = Text(self._perf_startup_footer(startup), style="dim")
        return Panel(
            Group(table, footer),
            title=title,
            border_style=_CYAN,
            width=width,
            padding=(0, 1),
        )

    @staticmethod
    def _perf_startup_footer(startup: Any) -> str:
        noun = "session" if startup.sessions == 1 else "sessions"
        if startup.slowest is None:
            return f"{startup.sessions} {noun}"
        tab = startup.slowest.initial_tab or "unknown"
        when = format_local(startup.slowest.ts, "%b %d %H:%M")
        return (
            f"{startup.sessions} {noun} · slowest {tab} at {when} "
            f"({format_duration(startup.slowest.visible_ready_seconds)})"
        )

    def _perf_stalls_panel(self, perf: Any, *, width: int) -> Panel:
        stalls = perf.stalls
        title = "Stalls & hitches"
        if not stalls.available:
            return self._perf_section_empty(
                title,
                width=width,
                source="stalls",
                coverage=perf.coverage,
                border_style=_ACCENT,
            )
        table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
        table.add_column("Event", style="bold", min_width=14, ratio=1)
        table.add_column("Count", justify="right", style=_CYAN, min_width=5)
        table.add_column("Worst", justify="right", min_width=5)
        table.add_column("Median", justify="right", min_width=6)
        table.add_column("Last seen", justify="right", min_width=8)
        for row in stalls.events:
            table.add_row(
                row.event,
                str(row.count),
                self._perf_duration(row.worst_seconds),
                self._perf_duration(row.median_seconds),
                self._perf_timestamp(row.last_seen_ts),
            )
        extras: list[Text] = []
        suppressed = [
            f"{row.event} +{row.suppressed_count} suppressed"
            for row in stalls.events
            if row.suppressed_count
        ]
        if suppressed:
            extras.append(Text(" · ".join(suppressed), style="dim"))
        if stalls.top_contexts:
            ranked = Text("Top context  ", style="bold")
            for index, context in enumerate(stalls.top_contexts):
                if index:
                    ranked.append("  ·  ", style="dim")
                ranked.append(context.name, style=categorical_color(context.name))
                ranked.append(f" ×{context.count}", style="dim")
            extras.append(ranked)
        if stalls.recovery_count:
            noun = "recovery" if stalls.recovery_count == 1 else "recoveries"
            extras.append(Text(f"{stalls.recovery_count} {noun}", style="dim"))
        body: list[Any] = [table, *extras]
        return Panel(
            Group(*body),
            title=title,
            border_style=_ACCENT,
            width=width,
            padding=(0, 1),
        )

    def _perf_latency_panel(self, perf: Any, *, width: int) -> Panel:
        latency = perf.latency
        group_label = _PERF_GROUP_LABELS.get(latency.group_by, "By Subsystem")
        title = f"Latency & reliability · {group_label}"
        if not perf.coverage.telemetry.enabled:
            return self._perf_message_panel(
                title,
                _DISABLED_TELEMETRY_MESSAGE,
                width=width,
                border_style=_GOLD,
            )
        if not latency.available:
            return self._perf_section_empty(
                title,
                width=width,
                recording_started_at=perf.coverage.telemetry.earliest_sample_ts,
                border_style=_GOLD,
            )
        show_tokens = latency.group_by == "provider"
        table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
        table.add_column("Row", style="bold", ratio=1)
        table.add_column("p50", justify="right", style=_CYAN)
        table.add_column("p95", justify="right", style=_CYAN)
        table.add_column("max", justify="right")
        table.add_column("Count", justify="right")
        table.add_column("Err%", justify="right")
        table.add_column("Retry%", justify="right")
        if show_tokens:
            table.add_column("Tok in", justify="right")
            table.add_column("Tok out", justify="right")
            table.add_column("Cache", justify="right")
        table.add_column("Share", ratio=1)
        bar_width = max(6, min(14, width - (72 if show_tokens else 48)))
        for row in latency.rows:
            color = (
                status_color(row.status) if row.status else categorical_color(row.key)
            )
            values = [
                Text(row.label, style=f"bold {color}"),
                Text(self._perf_duration(row.p50), style=color),
                Text(self._perf_duration(row.p95), style=color),
                Text(self._perf_duration(row.max), style=color),
                Text(str(row.count), style=color),
                Text(self._perf_rate(row.error_rate), style=color),
                Text(self._perf_rate(row.retry_rate), style=color),
            ]
            if show_tokens:
                values.extend(
                    (
                        Text(self._perf_token_count(row.tokens_in), style=color),
                        Text(self._perf_token_count(row.tokens_out), style=color),
                        Text(self._perf_cache_share(row), style=color),
                    )
                )
            values.append(self._share_bar(row.share, 1.0, width=bar_width))
            table.add_row(*values)
        return Panel(
            table, title=title, border_style=_GOLD, width=width, padding=(0, 1)
        )

    def _perf_coverage_panel(self, perf: Any, *, width: int) -> Panel:
        coverage = perf.coverage
        parts: list[Any] = []
        for note in coverage.notes:
            parts.append(Text(note, style=f"dim {_GOLD}"))
        parts.append(self._perf_telemetry_strip(coverage.telemetry))
        parts.append(self._perf_logs_table(coverage.logs))
        parts.append(self._perf_probes_text(coverage.probes))
        return Panel(
            Group(*parts),
            title="Data & instrumentation",
            border_style=_GREEN,
            width=width,
            padding=(0, 1),
        )

    def _perf_telemetry_strip(self, telemetry: Any) -> Text:
        line = Text()
        line.append("Telemetry  ", style="bold")
        if not telemetry.enabled:
            line.append("disabled", style=f"bold {_GOLD}")
            line.append(" · telemetry.enabled", style="dim")
            if telemetry.error:
                line.append(f" · {telemetry.error}", style="dim")
            return line
        line.append("enabled", style=f"bold {_GREEN}")
        if telemetry.resolution:
            line.append(f" · {telemetry.resolution}", style=_CYAN)
        if telemetry.store_size_bytes:
            line.append(f" · {format_bytes(telemetry.store_size_bytes)}", style="dim")
        line.append(
            f" · {telemetry.raw_sample_count} raw / "
            f"{telemetry.rollup_5m_count} 5m / "
            f"{telemetry.rollup_1h_count} 1h",
            style="dim",
        )
        freshness = self._perf_write_freshness(telemetry)
        if freshness:
            line.append(f" · {freshness}", style="dim")
        if telemetry.error:
            line.append(f" · {telemetry.error}", style=f"bold {_GOLD}")
        return line

    @staticmethod
    def _perf_write_freshness(telemetry: Any) -> str:
        pieces: list[str] = []
        if telemetry.last_write_age_seconds is not None:
            pieces.append(f"{format_duration(telemetry.last_write_age_seconds)} ago")
        elif telemetry.last_write_ts is not None:
            pieces.append(format_local(telemetry.last_write_ts, "%b %d %H:%M"))
        if telemetry.last_write_by_subsystem:
            named = ", ".join(
                f"{name} {format_local(stamp, '%b %d %H:%M')}"
                for name, stamp in telemetry.last_write_by_subsystem
            )
            pieces.append(named)
        return " · ".join(piece for piece in pieces if piece)

    def _perf_logs_table(self, logs: Any) -> Table | Text:
        if not logs:
            return Text("Logs  no coverage entries", style="dim italic")
        by_source = {entry.source: entry for entry in logs}
        table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
        table.add_column("Log", style="bold")
        table.add_column("Present", justify="right")
        table.add_column("In window", justify="right", style=_CYAN)
        table.add_column("Earliest", justify="right")
        table.add_column("Notes", ratio=1)
        ordered = [by_source[name] for name in _LOG_SOURCE_ORDER if name in by_source]
        ordered.extend(
            entry for entry in logs if entry.source not in set(_LOG_SOURCE_ORDER)
        )
        for entry in ordered:
            notes: list[str] = []
            if entry.truncated:
                notes.append("truncated")
            if entry.malformed_skipped:
                notes.append(f"{entry.malformed_skipped} unreadable")
            table.add_row(
                entry.source,
                "yes" if entry.present else "absent",
                str(entry.records_in_window),
                self._perf_timestamp(entry.earliest_ts),
                ", ".join(notes) or "—",
            )
        return table

    @staticmethod
    def _perf_probes_text(probes: Any) -> Text:
        line = Text()
        line.append("Probes  ", style="bold")
        if not probes:
            line.append("none reported", style="dim italic")
            return line
        for index, probe in enumerate(probes):
            if index:
                line.append("  ·  ", style="dim")
            state = "on" if probe.enabled else "off"
            color = _GREEN if probe.enabled else _MUTED
            line.append(f"{probe.name} {state}", style=color)
            if not probe.enabled:
                line.append(f" — {probe.hint}", style="dim")
        return line

    def _perf_unavailable_renderable(self) -> Panel:
        refresh_key = self._effective_key("refresh")
        retry = Text()
        retry.append(f"Press {refresh_key}", style=f"bold {_ACCENT}")
        retry.append(" to retry.")
        return Panel(
            Align.center(
                Group(
                    Text("No Perf snapshot is available.", style="dim italic"),
                    retry,
                ),
                vertical="middle",
            ),
            title="Perf",
            border_style="#444444",
            height=max(8, int(self.size.height or 24) - 11),
        )

    def _perf_section_empty(
        self,
        title: str,
        *,
        width: int,
        coverage: Any | None = None,
        source: str | None = None,
        recording_started_at: float | None = None,
        border_style: str,
    ) -> Panel:
        log = None
        if coverage is not None and source is not None:
            log = next(
                (entry for entry in coverage.logs if entry.source == source),
                None,
            )
        if log is not None and not log.present:
            message = f"No {source} log on disk."
            return self._perf_message_panel(
                title, message, width=width, border_style=border_style
            )
        body = empty_state(
            recording_started_at,
            width=max(16, width - 4),
            multiline=True,
        )
        return Panel(
            Align.center(body, vertical="middle"),
            title=title,
            border_style=border_style,
            width=width,
            padding=(0, 1),
        )

    @staticmethod
    def _perf_message_panel(
        title: str,
        message: str,
        *,
        width: int,
        border_style: str,
    ) -> Panel:
        return Panel(
            Align.center(
                Text(message, style=f"italic {_MUTED}", justify="center"),
                vertical="middle",
            ),
            title=title,
            border_style=border_style,
            width=width,
            padding=(0, 1),
        )

    @staticmethod
    def _perf_empty_tile(
        caption: str,
        *,
        width: int,
        message: str = "no samples in range",
        height: int = 6,
    ) -> Panel:
        return Panel(
            Align.center(
                Text(message, style=f"italic {_MUTED}", justify="center"),
                vertical="middle",
            ),
            title=caption,
            border_style="#444444",
            width=width,
            height=height,
            padding=0,
        )

    @staticmethod
    def _perf_duration(value: float | None) -> str:
        return "—" if value is None else format_duration(value)

    @staticmethod
    def _perf_rate(value: float | None) -> str:
        return "—" if value is None else format_percentage(value)

    @staticmethod
    def _perf_token_count(value: int | None) -> str:
        return "—" if value is None else format_tokens(value)

    @staticmethod
    def _perf_cache_share(row: Any) -> str:
        if row.cache_read_share is None:
            return "—"
        return format_percentage(row.cache_read_share * 100.0)

    @staticmethod
    def _perf_timestamp(value: float | None) -> str:
        return "—" if value is None else format_local(value, "%b %d %H:%M")


__all__ = ["StatisticsPerfRenderingMixin"]
