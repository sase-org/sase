"""``sase chats list`` — list recent chat transcripts."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.history.chat_catalog import (
    ChatTranscriptInfo,
    chat_info_to_json,
    list_chat_transcripts,
)

_PRETTY_SNIPPET_MAX_CHARS = 60


def handle_chats_list(args: argparse.Namespace) -> None:
    """Render the chat catalog (pretty table or JSON)."""
    limit: int | None = getattr(args, "limit", None)
    query: str | None = getattr(args, "query", None)
    as_json = bool(getattr(args, "json", False))

    infos = list_chat_transcripts(limit=limit, query=query)

    if as_json:
        _print_json(infos)
        return

    _print_pretty(infos)


def _print_json(infos: list[ChatTranscriptInfo]) -> None:
    payload = [chat_info_to_json(info) for info in infos]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _print_pretty(infos: list[ChatTranscriptInfo]) -> None:
    console = Console()
    title = f"Chat Transcripts ({len(infos)})"

    if not infos:
        console.print(
            Panel(
                Text.from_markup("[dim]No chat transcripts found.[/dim]"),
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("BASENAME", style="bold")
    table.add_column("WORKFLOW")
    table.add_column("AGENT")
    table.add_column("MTIME")
    table.add_column("PROMPT")

    for info in infos:
        table.add_row(
            info.basename,
            info.workflow or "-",
            info.agent or "-",
            info.mtime,
            _truncate(info.prompt_snippet, _PRETTY_SNIPPET_MAX_CHARS),
        )

    console.print(Panel(table, title=title, border_style="cyan"))


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"
