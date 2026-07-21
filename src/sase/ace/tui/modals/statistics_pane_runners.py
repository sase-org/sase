"""Pure runner-occupancy presentation for the Statistics pane."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

from rich import box
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry.render import format_duration

from .statistics_pane_data import StatisticsViewData

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"
_RED = "#FF5F5F"
_MUTED = "#666666"
_VERTICAL_PARTIALS = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")
_HORIZONTAL_PARTIALS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")


@dataclass(frozen=True, slots=True)
class _RunnerPlotColumn:
    """One width-bounded timeline column derived from contiguous slices."""

    average_runners: float
    peak_runners: int


def _time_at_or_above_current_limit(runners: Any) -> tuple[float, float]:
    """Return exact occupancy time/share compared with today's global limit."""
    limit = runners.current_limit
    if limit is None or limit <= 0:
        return 0.0, 0.0
    seconds = sum(row.seconds for row in runners.distribution if row.runners >= limit)
    window_seconds = max(0.0, runners.end_ts - runners.start_ts)
    return seconds, seconds / window_seconds if window_seconds else 0.0


def _busiest_runner_slices(trend: Sequence[Any]) -> tuple[Any, ...]:
    """Rank slices by peak, average, then chronological time."""
    return tuple(
        sorted(
            trend,
            key=lambda slice_: (
                -slice_.peak_runners,
                -slice_.average_runners,
                slice_.start_ts,
                slice_.end_ts,
                slice_.label,
            ),
        )
    )


def _compress_runner_trend(
    trend: Sequence[Any],
    *,
    width: int,
) -> tuple[_RunnerPlotColumn, ...]:
    """Compress contiguous slices to at most ``width`` time-weighted columns."""
    if width <= 0 or not trend:
        return ()
    if width >= len(trend):
        return tuple(
            _RunnerPlotColumn(
                average_runners=trend[index * len(trend) // width].average_runners,
                peak_runners=trend[index * len(trend) // width].peak_runners,
            )
            for index in range(width)
        )
    column_count = width
    columns: list[_RunnerPlotColumn] = []
    for column_index in range(column_count):
        start = column_index * len(trend) // column_count
        end = max(start + 1, (column_index + 1) * len(trend) // column_count)
        slices = trend[start:end]
        durations = tuple(
            max(0.0, slice_.end_ts - slice_.start_ts) for slice_ in slices
        )
        total_seconds = sum(durations)
        if total_seconds:
            average = (
                sum(
                    slice_.average_runners * duration
                    for slice_, duration in zip(slices, durations, strict=True)
                )
                / total_seconds
            )
        else:
            average = sum(slice_.average_runners for slice_ in slices) / len(slices)
        columns.append(
            _RunnerPlotColumn(
                average_runners=average,
                peak_runners=max(slice_.peak_runners for slice_ in slices),
            )
        )
    return tuple(columns)


class StatisticsRunnersRenderingMixin:
    """Render runner metrics from the already-loaded immutable snapshot."""

    _project_filter: str | None
    _runners_stacked: bool
    size: Any

    def _runners_renderable(self, result: StatisticsViewData) -> Group:
        runners = result.views.runners
        available_width = max(76, int(self.size.width or 100) - 2)
        summary = self._runner_summary(runners, width=available_width)
        context = self._runner_context(runners)
        if self._runners_stacked:
            timeline_width = available_width
            middle: Any = Group(
                self._runner_timeline(result, width=timeline_width),
                self._runner_occupancy(runners, width=available_width),
            )
        else:
            section_width = max(36, (available_width - 2) // 2)
            middle = Columns(
                (
                    self._runner_timeline(result, width=section_width),
                    self._runner_occupancy(runners, width=section_width),
                ),
                equal=True,
                expand=True,
                width=section_width,
            )
        return Group(
            summary,
            *context,
            middle,
            self._runner_busiest_slices(runners),
        )

    def _runner_summary(self, runners: Any, *, width: int) -> Columns:
        at_limit_seconds, at_limit_share = _time_at_or_above_current_limit(runners)
        tile_width = max(14, (width - 4) // 5)
        limit_caption = "Global limit now" if self._project_filter else "Current limit"
        if runners.current_limit is None:
            limit_value = "—"
            limit_detail = "reference unavailable"
            limit_color = _MUTED
        else:
            limit_value = f"{runners.current_limit} runners"
            limit_detail = (
                f"{format_duration(at_limit_seconds)} · "
                f"{at_limit_share * 100:.1f}% at/above"
            )
            limit_color = (
                _RED if runners.peak_runners > runners.current_limit else _GOLD
            )
        cards = (
            self._runner_summary_card(
                "Peak",
                f"{runners.peak_runners} runners",
                f"{format_duration(runners.peak_seconds)} at peak",
                color=_ACCENT,
                width=tile_width,
            ),
            self._runner_summary_card(
                "Average",
                f"{runners.average_runners:.2f} runners",
                "wall-time weighted",
                color=_CYAN,
                width=tile_width,
            ),
            self._runner_summary_card(
                "Busy",
                f"{runners.busy_share * 100:.1f}%",
                f"{format_duration(runners.busy_seconds)} busy",
                color=_GREEN,
                width=tile_width,
            ),
            self._runner_summary_card(
                "Runner time",
                format_duration(runners.runner_seconds),
                "integrated occupancy",
                color=_CYAN,
                width=tile_width,
            ),
            self._runner_summary_card(
                limit_caption,
                limit_value,
                limit_detail,
                color=limit_color,
                width=tile_width,
            ),
        )
        return Columns(cards, equal=True, expand=True, width=tile_width)

    @staticmethod
    def _runner_summary_card(
        caption: str,
        value: str,
        detail: str,
        *,
        color: str,
        width: int,
    ) -> Panel:
        compact = width < 20
        body: list[Text] = []
        if compact:
            body.append(Text(caption, style="bold", justify="center"))
        body.extend(
            (
                Text(value, style=f"bold {color}", justify="center"),
                Text(detail, style="dim", justify="center"),
            )
        )
        return Panel(
            Group(*body),
            title=None if compact else caption,
            border_style=color,
            width=width,
            height=6 if compact else 5,
            padding=0,
        )

    def _runner_context(self, runners: Any) -> tuple[Text, ...]:
        notes: list[Text] = []
        if runners.current_limit is not None:
            if self._project_filter:
                notes.append(
                    Text(
                        "Current limit is today's global reference, not project-specific "
                        "capacity or a historical limit.",
                        style=f"dim {_GOLD}",
                    )
                )
            else:
                notes.append(
                    Text(
                        "Current limit is today's global reference, not a historical "
                        "limit.",
                        style=f"dim {_GOLD}",
                    )
                )
            if runners.peak_runners > runners.current_limit:
                notes.append(
                    Text(
                        f"Observed peak {runners.peak_runners} exceeds today's current "
                        f"global limit {runners.current_limit}; the chart scale expands "
                        "to show it.",
                        style=f"bold {_RED}",
                    )
                )
        skipped = runners.malformed_rows_skipped + runners.invalid_intervals_skipped
        if skipped:
            notes.append(
                Text(
                    "Partial valid snapshot: skipped "
                    f"{runners.malformed_rows_skipped} malformed rows and "
                    f"{runners.invalid_intervals_skipped} invalid intervals.",
                    style=f"dim {_GOLD}",
                )
            )
        return tuple(notes)

    def _runner_timeline(self, result: StatisticsViewData, *, width: int) -> Panel:
        runners = result.views.runners
        scale = max(
            1,
            runners.peak_runners,
            runners.current_limit or 0,
        )
        chart_height = 6
        axis_width = max(1, len(str(scale)))
        plot_width = max(8, width - axis_width - 4)
        columns = _compress_runner_trend(runners.trend, width=plot_width)

        legend = Text(no_wrap=True, overflow="crop")
        legend.append("█ average", style=_CYAN)
        legend.append("  ◆ peak", style=_ACCENT)
        if runners.current_limit is not None:
            legend.append("  ─ limit now", style=_GOLD)
        legend.append(f"  ·  fixed 0–{scale}", style="dim")

        chart_rows: list[Text] = []
        limit_row = self._runner_value_row(
            runners.current_limit,
            scale=scale,
            height=chart_height,
        )
        for row_index in range(chart_height):
            row = Text(no_wrap=True, overflow="crop")
            axis_label = str(scale) if row_index == 0 else ""
            if row_index == limit_row and runners.current_limit != scale:
                axis_label = str(runners.current_limit)
            axis_style = _GOLD if row_index == limit_row else "#888888"
            row.append(axis_label.rjust(axis_width), style=axis_style)
            row.append("┤", style=axis_style)
            for column in columns:
                peak_row = self._runner_value_row(
                    column.peak_runners,
                    scale=scale,
                    height=chart_height,
                )
                if peak_row == row_index:
                    row.append("◆", style=f"bold {_ACCENT}")
                    continue
                if limit_row == row_index:
                    row.append("─", style=_GOLD)
                    continue
                units = column.average_runners / scale * chart_height
                from_bottom = chart_height - row_index - 1
                fill = min(1.0, max(0.0, units - from_bottom))
                glyph = _VERTICAL_PARTIALS[round(fill * 8)]
                row.append(glyph, style=_CYAN)
            chart_rows.append(row)
        baseline = Text(no_wrap=True, overflow="crop")
        baseline.append("0".rjust(axis_width), style="#888888")
        baseline.append("└", style="#888888")
        baseline.append("─" * len(columns), style="#888888")
        chart_rows.append(baseline)

        if runners.trend:
            trend_context = (
                f"{runners.trend[0].label} → {runners.trend[-1].label} · "
                f"{len(runners.trend)} slices"
            )
        else:
            trend_context = "No trend slices returned"
        footer = Text(
            f"{trend_context} · {result.selected_range.display_label} · "
            f"{result.selected_range.label}",
            style="dim",
        )
        return Panel(
            Group(legend, *chart_rows, footer),
            title="Concurrency over time",
            border_style=_CYAN,
            width=width,
            padding=(0, 1),
        )

    @staticmethod
    def _runner_value_row(
        value: int | None,
        *,
        scale: int,
        height: int,
    ) -> int | None:
        if value is None or value <= 0:
            return None
        scaled = min(1.0, max(0.0, value / scale))
        return max(0, min(height - 1, height - ceil(scaled * height)))

    def _runner_occupancy(self, runners: Any, *, width: int) -> Panel:
        table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
        table.add_column("Runners", justify="right")
        table.add_column("Duration", justify="right")
        table.add_column("Share", justify="right")
        table.add_column("Distribution", ratio=1)
        bar_width = max(6, min(18, width - 32))
        for row in runners.distribution:
            color = self._runner_occupancy_color(row.runners, runners.current_limit)
            runner_label = "0 · idle" if row.runners == 0 else str(row.runners)
            table.add_row(
                Text(runner_label, style=f"bold {color}" if row.runners else color),
                Text(format_duration(row.seconds), style=color),
                Text(f"{row.share * 100:.2f}%", style=color),
                self._runner_share_bar(row.share, width=bar_width, color=color),
            )
        body: list[Any] = [table]
        if runners.current_limit is not None:
            body.append(
                Text(
                    "Gold/red rows compare with today's current global limit; they do "
                    "not imply historical saturation or project capacity.",
                    style=f"dim {_GOLD}",
                )
            )
        return Panel(
            Group(*body),
            title="Occupancy by runner count",
            border_style=_ACCENT,
            width=width,
            padding=(0, 1),
        )

    @staticmethod
    def _runner_occupancy_color(runners: int, current_limit: int | None) -> str:
        if runners == 0:
            return _MUTED
        if current_limit is not None and runners > current_limit:
            return _RED
        if current_limit is not None and runners == current_limit:
            return _GOLD
        return _CYAN if runners == 1 else _ACCENT

    @staticmethod
    def _runner_share_bar(share: float, *, width: int, color: str) -> Text:
        ratio = min(1.0, max(0.0, share))
        eighths = round(ratio * width * 8)
        full, remainder = divmod(eighths, 8)
        full = min(width, full)
        glyphs = "█" * full
        if full < width:
            glyphs += _HORIZONTAL_PARTIALS[remainder]
        text = Text(glyphs, style=color)
        text.append("░" * max(0, width - len(glyphs)), style="#333333")
        return text

    @staticmethod
    def _runner_busiest_slices(runners: Any) -> Panel:
        table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
        table.add_column("Slice", style="bold", ratio=1)
        table.add_column("Peak", justify="right", style=_ACCENT)
        table.add_column("Average", justify="right", style=_CYAN)
        table.add_column("Busy", justify="right")
        table.add_column("Runner time", justify="right")
        for slice_ in _busiest_runner_slices(runners.trend):
            table.add_row(
                slice_.label,
                str(slice_.peak_runners),
                f"{slice_.average_runners:.2f}",
                format_duration(slice_.busy_seconds),
                format_duration(slice_.runner_seconds),
            )
        return Panel(
            table,
            title="Busiest slices · peak → average → time",
            border_style=_GOLD,
        )


__all__ = ["StatisticsRunnersRenderingMixin"]
