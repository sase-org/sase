"""``sase chat list`` — list recent chat transcripts."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.history.chat_catalog import chat_info_to_json
from sase.history.chat_catalog_provenance import (
    CHAT_PROVENANCE_VALUES,
    ChatCatalogEntry,
    ChatProvenance,
    chat_provenance_badge,
    load_chat_catalog,
)

_PRETTY_SNIPPET_MAX_CHARS = 60
# Widest badge is ``↓ remote``; widest header is ``MACHINE``.
_SYNC_COLUMN_WIDTH = 8
_MACHINE_COLUMN_WIDTH = 10
# ``YYYY-MM-DD HH:MM`` — sub-minute precision and the UTC offset are noise in a
# table and cost the width that BASENAME and PROMPT need.
_MTIME_COLUMN_WIDTH = 16


def handle_chat_list(args: argparse.Namespace) -> None:
    """Render the chat catalog (pretty table or JSON)."""
    limit: int | None = getattr(args, "limit", None)
    query: str | None = getattr(args, "query", None)
    machine: str | None = getattr(args, "machine", None)
    provenance = _resolve_provenance(getattr(args, "provenance", None))
    as_json = bool(getattr(args, "json", False))

    snapshot = load_chat_catalog(
        limit=limit,
        query=query,
        provenance=provenance,
        machine=machine,
    )
    entries = list(snapshot.entries)

    if as_json:
        _print_json(entries)
        return

    _print_pretty(entries)


def _resolve_provenance(raw: object) -> ChatProvenance | None:
    """Narrow an argparse value to a :data:`ChatProvenance` literal.

    ``argparse`` already rejects anything outside ``choices``, so an
    unrecognized value simply means "no provenance filter".
    """
    if not isinstance(raw, str) or not raw:
        return None
    for value in CHAT_PROVENANCE_VALUES:
        if value == raw:
            return value
    return None


def _print_json(entries: list[ChatCatalogEntry]) -> None:
    payload = [chat_info_to_json(entry) for entry in entries]
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        present_agent_name,
    )

    identity = AgentIdentitySnapshot.current()
    for item in payload:
        agent = item.get("agent")
        if isinstance(agent, str):
            item["agent"] = present_agent_name(agent, identity)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _print_pretty(entries: list[ChatCatalogEntry]) -> None:
    console = Console()
    title = f"Chat Transcripts ({len(entries)})"

    if not entries:
        console.print(
            Panel(
                Text.from_markup("[dim]No chat transcripts found.[/dim]"),
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    # Fixed-width, no-wrap columns are exempt from Rich's width collapsing, so
    # a narrow terminal reflows BASENAME/WORKFLOW/AGENT/PROMPT instead of
    # squeezing the provenance encoding down to an ellipsis.
    table.add_column("SYNC", no_wrap=True, width=_SYNC_COLUMN_WIDTH)
    table.add_column("BASENAME", style="bold")
    table.add_column("WORKFLOW")
    table.add_column("AGENT")
    table.add_column("MACHINE", no_wrap=True, width=_MACHINE_COLUMN_WIDTH)
    table.add_column("MTIME", no_wrap=True, width=_MTIME_COLUMN_WIDTH)
    table.add_column("PROMPT")

    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        present_agent_name,
    )

    identity = AgentIdentitySnapshot.current()

    for entry in entries:
        table.add_row(
            _sync_cell(entry),
            entry.basename,
            entry.workflow or "-",
            present_agent_name(entry.agent, identity) if entry.agent else "-",
            entry.source_machine or "-",
            _pretty_mtime(entry.mtime),
            _truncate(entry.prompt_snippet, _PRETTY_SNIPPET_MAX_CHARS),
        )

    console.print(Panel(table, title=title, border_style="cyan"))


def _pretty_mtime(mtime: str) -> str:
    """Trim an ISO mtime to minute precision for the table.

    The full value (including sub-second precision and the UTC offset) stays
    in the JSON output; only the human-facing table is shortened.
    """
    if len(mtime) < _MTIME_COLUMN_WIDTH:
        return mtime
    return mtime[:_MTIME_COLUMN_WIDTH].replace("T", " ")


def _sync_cell(entry: ChatCatalogEntry) -> Text:
    """Render the three-channel provenance badge for one row."""
    badge = chat_provenance_badge(entry.provenance)
    return Text(f"{badge.glyph} {badge.label}", style=badge.color)


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"
