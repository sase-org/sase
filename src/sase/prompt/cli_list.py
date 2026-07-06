"""``sase prompt list`` — list recent prompts (pretty table or JSON)."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.history.prompt import PromptHistoryRecord, list_prompt_records
from sase.project_display_names import humanize_vcs_refs_in_text
from sase.prompt.render import format_timestamp, prompt_preview, record_to_json


def handle_prompt_list(args: argparse.Namespace) -> None:
    """Render the prompt catalog (pretty table or JSON)."""
    include_cancelled = bool(getattr(args, "all", False))
    cancelled_only = bool(getattr(args, "cancelled", False))
    query: str | None = getattr(args, "query", None)
    limit: int | None = getattr(args, "limit", None)
    as_json = bool(getattr(args, "json", False))

    records = list_prompt_records(
        include_cancelled=include_cancelled,
        cancelled_only=cancelled_only,
        query=query,
        limit=limit,
    )

    if as_json:
        _print_json(records)
        return

    _print_pretty(records)


def _print_json(records: list[PromptHistoryRecord]) -> None:
    payload = [record_to_json(record) for record in records]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _hints_text(record: PromptHistoryRecord) -> Text:
    """Build a colored chip summary (project / xprompt / directive)."""
    text = Text()
    try:
        from sase.history.prompt_metadata import summarize_prompt_for_list

        summary = summarize_prompt_for_list(humanize_vcs_refs_in_text(record.text))
    except Exception:
        return text

    parts: list[tuple[str, str]] = []
    if summary.project_prefix:
        ref = summary.project_prefix
        if summary.project_ref_display:
            ref = f"{summary.project_prefix}{summary.project_ref_display}"
        parts.append((ref, "blue"))
    parts.extend((chip, "green") for chip in summary.xprompts)
    if summary.directive_token:
        parts.extend((tok, "yellow") for tok in summary.directive_token.split())

    for index, (value, style) in enumerate(parts):
        if index:
            text.append(" ")
        text.append(value, style=style)
    return text


def _print_pretty(records: list[PromptHistoryRecord]) -> None:
    console = Console()
    title = f"Prompts ({len(records)})"

    if not records:
        console.print(
            Panel(
                Text.from_markup("[dim]No prompts found.[/dim]"),
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("LAST USED", style="dim", no_wrap=True)
    table.add_column("STATUS", no_wrap=True)
    table.add_column("CHARS", justify="right", style="dim", no_wrap=True)
    table.add_column("HINTS", no_wrap=True)
    table.add_column("PREVIEW")

    for record in records:
        cancelled = record.cancelled
        status = (
            Text("cancelled", style="magenta")
            if cancelled
            else Text("launched", style="green")
        )
        preview_style = "magenta dim" if cancelled else ""
        table.add_row(
            record.id,
            format_timestamp(record.last_used),
            status,
            str(record.text_chars),
            _hints_text(record),
            Text(
                prompt_preview(humanize_vcs_refs_in_text(record.text)),
                style=preview_style,
            ),
        )

    console.print(Panel(table, title=title, border_style="cyan"))
