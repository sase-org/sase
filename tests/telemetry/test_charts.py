"""Tests for ``sase.telemetry.charts`` — chart rendering functions."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.telemetry.charts import (
    render_bar_chart,
    render_line_chart,
    render_sparkline,
)
from sase.telemetry.prom_query import TimeSeries

# ── Helpers ──────────────────────────────────────────────────────────


def _render_to_str(renderable: Panel | Text) -> str:
    console = Console(file=None, force_terminal=False, width=120)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


# ── render_line_chart ────────────────────────────────────────────────


def test_line_chart_with_data() -> None:
    series = [
        TimeSeries(
            metric="test",
            points=[(1.0, 10.0), (2.0, 20.0), (3.0, 15.0)],
        )
    ]
    panel = render_line_chart(series, title="Test Chart", y_label="count")
    output = _render_to_str(panel)
    assert "Test Chart" in output


def test_line_chart_multi_series() -> None:
    series = [
        TimeSeries(metric="a", points=[(1.0, 10.0), (2.0, 20.0)]),
        TimeSeries(metric="b", points=[(1.0, 5.0), (2.0, 15.0)]),
    ]
    panel = render_line_chart(
        series,
        title="Multi",
        legend_labels=["series-a", "series-b"],
    )
    output = _render_to_str(panel)
    assert "Multi" in output


def test_line_chart_empty_data() -> None:
    panel = render_line_chart([], title="Empty")
    output = _render_to_str(panel)
    assert "Empty" in output
    assert "No data" in output


def test_line_chart_all_empty_series() -> None:
    series = [TimeSeries(metric="x", points=[])]
    panel = render_line_chart(series, title="No Points")
    output = _render_to_str(panel)
    assert "No data" in output


# ── render_bar_chart ─────────────────────────────────────────────────


def test_bar_chart_with_data() -> None:
    panel = render_bar_chart(
        labels=["ok", "error", "retry"],
        values=[100, 5, 3],
        title="Status Breakdown",
    )
    output = _render_to_str(panel)
    assert "Status Breakdown" in output


def test_bar_chart_empty() -> None:
    panel = render_bar_chart(labels=[], values=[], title="Empty Bar")
    output = _render_to_str(panel)
    assert "Empty Bar" in output
    assert "No data" in output


# ── render_sparkline ─────────────────────────────────────────────────


def test_sparkline_with_data() -> None:
    text = render_sparkline([1, 3, 5, 2, 4, 6, 3, 1], title="Load")
    output = _render_to_str(text)
    assert "Load" in output
    # Last value should be shown
    assert "1" in output


def test_sparkline_empty() -> None:
    text = render_sparkline([], title="Empty")
    output = _render_to_str(text)
    assert "Empty" in output
    # Should show placeholder bars
    assert "▁" in output


def test_sparkline_constant_values() -> None:
    text = render_sparkline([5, 5, 5, 5], title="Flat")
    output = _render_to_str(text)
    assert "Flat" in output
    assert "5" in output
