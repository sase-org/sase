"""Chart rendering for the telemetry dashboard.

Uses ``plotext`` to render terminal charts embedded inside Rich panels.
"""

from __future__ import annotations

import plotext as plt  # type: ignore[import-untyped,import-not-found]
from rich.panel import Panel
from rich.text import Text

from sase.telemetry.prom_query import TimeSeries

# Consistent color palette for multi-series charts.
COLORS = ["cyan", "magenta", "green", "yellow", "red", "blue", "orange", "white"]


def render_line_chart(
    series: list[TimeSeries],
    title: str,
    y_label: str = "",
    width: int = 60,
    height: int = 12,
    legend_labels: list[str] | None = None,
) -> Panel:
    """Render a multi-series line chart inside a Rich Panel."""
    plt.clear_figure()
    plt.plotsize(width, height)
    plt.theme("dark")
    plt.title("")

    if not series or all(len(s.points) == 0 for s in series):
        return _empty_panel(title, width, height)

    for i, ts in enumerate(series):
        if not ts.points:
            continue
        xs = [p[0] for p in ts.points]
        ys = [p[1] for p in ts.points]
        label = (
            legend_labels[i]
            if legend_labels and i < len(legend_labels)
            else ts.labels.get("__display__", ts.metric)
        )
        color = COLORS[i % len(COLORS)]
        plt.plot(xs, ys, label=label, color=color)

    if y_label:
        plt.ylabel(y_label)
    plt.xlabel("time")

    return Panel(
        Text.from_ansi(plt.build()),
        title=f"[bold]{title}[/bold]",
        border_style="bright_blue",
        padding=(0, 1),
    )


def render_bar_chart(
    labels: list[str],
    values: list[float],
    title: str,
    width: int = 60,
    height: int = 12,
    color: str = "cyan",
) -> Panel:
    """Render a bar chart inside a Rich Panel."""
    plt.clear_figure()
    plt.plotsize(width, height)
    plt.theme("dark")
    plt.title("")

    if not labels or not values:
        return _empty_panel(title, width, height)

    plt.bar(labels, values, color=color)

    return Panel(
        Text.from_ansi(plt.build()),
        title=f"[bold]{title}[/bold]",
        border_style="bright_blue",
        padding=(0, 1),
    )


def render_sparkline(values: list[float], title: str) -> Text:
    """Render a compact inline sparkline using Unicode block characters."""
    if not values:
        return Text(f"{title}: ▁▁▁▁▁▁▁▁", style="dim")

    mn = min(values)
    mx = max(values)
    span = mx - mn if mx != mn else 1.0
    blocks = " ▁▂▃▄▅▆▇█"

    chars: list[str] = []
    for v in values:
        idx = int((v - mn) / span * (len(blocks) - 1))
        chars.append(blocks[idx])

    spark = "".join(chars)
    last = values[-1]
    return Text.assemble(
        (f"{title}: ", "bold"),
        (spark, "cyan"),
        (f" {last:g}", "bright_white"),
    )


def _empty_panel(title: str, width: int, height: int) -> Panel:
    """Placeholder panel when no data is available."""
    msg = Text("No data available", style="dim italic", justify="center")
    return Panel(
        msg,
        title=f"[bold]{title}[/bold]",
        border_style="dim",
        width=width,
        height=height,
        padding=(height // 3, 1),
    )
