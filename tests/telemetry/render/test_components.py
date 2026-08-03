"""Golden-text tests for bars, sparklines, and stat tiles."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.telemetry.render import (
    Bar,
    render_bar_chart,
    render_sparkline,
    render_stat_tile,
    sparkline_glyphs,
)


def _render(renderable: Panel | Text) -> str:
    console = Console(file=None, force_terminal=False, color_system=None, width=100)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_sparkline_resamples_and_renders_golden_text() -> None:
    assert sparkline_glyphs([0, 1, 2, 3, 4], width=8) == "▁▂▃▄▅▆▇█"
    sparkline = render_sparkline([1, 3, 2, 5, 4], title="Load", width=24)

    assert _render(sparkline) == "Load: ▁▂▃▄▅▄▄▃▄▅▇███▇▇ 4\n"


def test_sparkline_constant_and_empty_states() -> None:
    assert sparkline_glyphs([5, 5, 5], width=6) == "▄▄▄▄▄▄"
    empty = render_sparkline([], title="Load", width=20)

    assert _render(empty) == "no samples in range \n"


def test_horizontal_bar_chart_golden_text() -> None:
    chart = render_bar_chart(
        [
            Bar("ok", "ok", 100, status="ok"),
            Bar("error", "error", 12, status="critical"),
            Bar("retry", "retry", 37),
        ],
        title="Status",
        width=42,
        height=8,
    )

    assert _render(chart) == (
        "╭──────────────── Status ────────────────╮\n"
        "│ok    █████████████████████████████ 100 │\n"
        "│error ███▌                           12 │\n"
        "│retry ██████████▊                    37 │\n"
        "│                                        │\n"
        "│                                        │\n"
        "│                                        │\n"
        "╰────────────────────────────────────────╯\n"
    )


def test_vertical_bar_chart_golden_text() -> None:
    chart = render_bar_chart(
        [
            Bar("a", "alpha", 10),
            Bar("b", "beta", 30),
            Bar("c", "gamma", 20),
        ],
        title="Vertical",
        width=36,
        height=10,
        orientation="vertical",
    )

    assert _render(chart) == (
        "╭──────────── Vertical ────────────╮\n"
        "│30┤          ██████████           │\n"
        "│  │          ██████████           │\n"
        "│  │          ██████████▅▅▅▅▅▅▅▅▅▅ │\n"
        "│  │          ████████████████████ │\n"
        "│  │▃▃▃▃▃▃▃▃▃▃████████████████████ │\n"
        "│  │██████████████████████████████ │\n"
        "│  │██████████████████████████████ │\n"
        "│   alpha     beta      gamma      │\n"
        "╰──────────────────────────────────╯\n"
    )


def test_stat_tile_golden_text() -> None:
    tile = render_stat_tile(
        42,
        caption="Active Agents",
        delta=12.5,
        sparkline=[1, 3, 2, 5],
        status="ok",
        width=24,
        height=7,
    )

    assert _render(tile) == (
        "╭─── Active Agents ────╮\n"
        "│          42          │\n"
        "│         ✓ ok         │\n"
        "│ ↑ 12.5% vs previous  │\n"
        "│ ▁▂▂▃▃▄▄▄▄▄▃▃▃▃▄▅▆▆▇█ │\n"
        "│                      │\n"
        "╰──────────────────────╯\n"
    )


def test_component_empty_state_includes_recording_time() -> None:
    started = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    chart = render_bar_chart(
        title="Empty",
        width=48,
        height=8,
        recording_started_at=started,
        timezone=UTC,
    )

    assert "telemetry began" in _render(chart)
    assert "recording 2026-07-17 12:00 UTC" in _render(chart)
