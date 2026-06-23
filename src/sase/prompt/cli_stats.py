"""``sase prompt stats`` — summarize the prompt-history store."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.history.prompt import (
    PromptHistoryStats,
    PromptLargest,
    compute_prompt_stats,
)
from sase.prompt.render import format_size, format_timestamp


def handle_prompt_stats(args: argparse.Namespace) -> None:
    """Render prompt-history statistics (pretty panel or JSON)."""
    stats = compute_prompt_stats()
    if bool(getattr(args, "json", False)):
        _print_json(stats)
        return
    _print_pretty(stats)


def _largest_to_json(item: PromptLargest) -> dict[str, object]:
    return {"id": item.id, "text_chars": item.text_chars, "preview": item.preview}


def _stats_to_json(stats: PromptHistoryStats) -> dict[str, object]:
    return {
        "path": stats.path,
        "exists": stats.exists,
        "size_bytes": stats.size_bytes,
        "shard_count": stats.shard_count,
        "total": stats.total,
        "launched": stats.launched,
        "cancelled": stats.cancelled,
        "oldest_last_used": stats.oldest_last_used,
        "newest_last_used": stats.newest_last_used,
        "length_percentiles": stats.length_percentiles,
        "largest": [_largest_to_json(item) for item in stats.largest],
        "top_chips": [[chip, count] for chip, count in stats.top_chips],
    }


def _print_json(stats: PromptHistoryStats) -> None:
    json.dump(_stats_to_json(stats), sys.stdout, indent=2)
    sys.stdout.write("\n")


def _print_pretty(stats: PromptHistoryStats) -> None:
    console = Console()

    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_column("k", style="bold cyan", no_wrap=True)
    summary.add_column("v")
    summary.add_row("path", stats.path)
    if not stats.exists:
        summary.add_row("status", "[yellow]no history file yet[/yellow]")
    summary.add_row("size", format_size(stats.size_bytes))
    summary.add_row("shards", str(stats.shard_count))
    summary.add_row("total", str(stats.total))
    summary.add_row("launched", f"[green]{stats.launched}[/green]")
    summary.add_row("cancelled", f"[magenta]{stats.cancelled}[/magenta]")
    summary.add_row("oldest", format_timestamp(stats.oldest_last_used or "-"))
    summary.add_row("newest", format_timestamp(stats.newest_last_used or "-"))
    pct = stats.length_percentiles
    summary.add_row(
        "length (chars)",
        f"p50={pct['p50']}  p90={pct['p90']}  p99={pct['p99']}  max={pct['max']}",
    )

    panels = [Panel(summary, title="Prompt History Stats", border_style="cyan")]

    if stats.largest:
        largest = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        largest.add_column("ID", style="cyan", no_wrap=True)
        largest.add_column("CHARS", justify="right", style="dim", no_wrap=True)
        largest.add_column("PREVIEW")
        for item in stats.largest:
            largest.add_row(item.id, str(item.text_chars), item.preview)
        panels.append(Panel(largest, title="Largest Prompts", border_style="cyan"))

    if stats.top_chips:
        chips = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        chips.add_column("CHIP", style="green", no_wrap=True)
        chips.add_column("COUNT", justify="right", style="dim", no_wrap=True)
        for chip, count in stats.top_chips:
            chips.add_row(chip, str(count))
        panels.append(Panel(chips, title="Top Chips", border_style="cyan"))

    for panel in panels:
        console.print(panel)
