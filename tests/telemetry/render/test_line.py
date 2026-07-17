"""Golden-text tests for deterministic braille line charts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.panel import Panel

from sase.telemetry.render import Point, Series, render_line_chart

_BASE = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _render(renderable: Panel) -> str:
    console = Console(file=None, force_terminal=False, color_system=None, width=100)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_empty_series_golden_text() -> None:
    chart = render_line_chart(
        [],
        title="Empty",
        width=48,
        height=8,
        recording_started_at=_BASE,
    )

    assert _render(chart) == (
        "╭─────────────────── Empty ────────────────────╮\n"
        "│                                              │\n"
        "│                                              │\n"
        "│    no samples in range — telemetry began     │\n"
        "│       recording 2026-07-17 12:00 UTC         │\n"
        "│                                              │\n"
        "│                                              │\n"
        "╰──────────────────────────────────────────────╯\n"
    )


def test_single_point_golden_text() -> None:
    chart = render_line_chart(
        [Series("only", (Point(_BASE, 5.0),), label="Only")],
        title="Single",
        width=36,
        height=9,
    )

    assert _render(chart) == (
        "╭───────────── Single ─────────────╮\n"
        "│● Only                            │\n"
        "│  6│                              │\n"
        "│   │                              │\n"
        "│   │               ⠂              │\n"
        "│   │                              │\n"
        "│  4│                              │\n"
        "│    07-17 11:59        07-17 12:01│\n"
        "╰──────────────────────────────────╯\n"
    )


def test_many_series_golden_text() -> None:
    series = [
        Series.from_pairs(
            f"s{index}",
            [(_BASE, index), (_BASE + timedelta(minutes=5), index + 1)],
            label=f"Series {index}",
        )
        for index in range(7)
    ]
    chart = render_line_chart(series, title="Many", width=50, height=10)

    assert _render(chart) == (
        "╭───────────────────── Many ─────────────────────╮\n"
        "│● Series 0  ● Series 1  ● Series 2  ● Series 3 …│\n"
        "│  7│⣀⣀⣀⣀⣀⣀⣀⡠⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠊⠉⢉⣉⣉⣉⣉⣉│\n"
        "│   │⣀⣀⣀⣀⣀⡠⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠔⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠊⠉⠉⠉⠉⠉⠉⠉⠉⢉⣉⣁⣀⣀⣀⣀⣀│\n"
        "│   │⠤⠤⠤⠤⠤⠤⠤⠔⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⡡⠤⠤⠤⠤⠤⠤⠤│\n"
        "│   │⠒⠒⠒⠒⠒⠒⠒⢊⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⣉⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠔⠒⠒⠒⠒⠒⠒⠒│\n"
        "│   │⠉⠉⠉⠉⠉⢉⣉⣁⣀⣀⣀⣀⣀⣀⣀⣀⡠⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠔⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠊⠉⠉⠉⠉⠉│\n"
        "│  0│⣉⣉⣉⣉⣉⣁⣀⡠⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠤⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠊⠉⠉⠉⠉⠉⠉⠉│\n"
        "│    07-17 12:00                      07-17 12:05│\n"
        "╰────────────────────────────────────────────────╯\n"
    )


def test_clipping_golden_text() -> None:
    series = Series.from_pairs(
        "latency",
        [
            (_BASE, -100),
            (_BASE + timedelta(minutes=1), 5),
            (_BASE + timedelta(minutes=2), 100),
        ],
        label="Latency",
    )
    chart = render_line_chart(
        [series],
        title="Clipped",
        width=40,
        height=9,
        y_min=0,
        y_max=10,
    )

    assert _render(chart) == (
        "╭────────────── Clipped ───────────────╮\n"
        "│● Latency                             │\n"
        "│ 10│                           ⢀⣀⠤⠤⠒⠒⠉│\n"
        "│   │                    ⣀⣀⠤⠔⠒⠊⠉⠁      │\n"
        "│   │             ⣀⡠⠤⠔⠒⠉⠉              │\n"
        "│   │      ⣀⣀⠤⠔⠒⠊⠉                     │\n"
        "│  0│⣀⠤⠤⠒⠊⠉                            │\n"
        "│    07-17 12:00            07-17 12:02│\n"
        "╰──────────────────────────────────────╯\n"
    )


def test_narrow_width_degrades_to_block_chart_golden_text() -> None:
    series = [
        Series.from_pairs(
            "alpha",
            [
                (_BASE + timedelta(minutes=index), value)
                for index, value in enumerate([1, 4, 2, 7, 5])
            ],
            label="Alpha",
        ),
        Series.from_pairs(
            "beta",
            [
                (_BASE + timedelta(minutes=index), value)
                for index, value in enumerate([6, 3, 5, 2, 4])
            ],
            label="Beta",
        ),
    ]
    chart = render_line_chart(series, title="Narrow", width=24, height=6)

    assert _render(chart) == (
        "╭─────── Narrow ───────╮\n"
        "│Alpha ▁▂▃▄▅▄▃▃▃▅▆██▇▇▆│\n"
        "│Beta  █▇▅▄▃▄▅▆▅▄▂▁▁▂▃▄│\n"
        "│                      │\n"
        "│                      │\n"
        "╰──────────────────────╯\n"
    )
