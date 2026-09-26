"""Rendering and JSON shapes for the ``sase gate`` shell command surface."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.time import get_timezone
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.naming import short_gate_turn_id
from sase.gate_turn.projection import (
    gate_turn_followup_needs_attention,
    gate_turn_runtime_json,
)
from sase.gate_turn.status import (
    effective_gate_status,
    gate_status_glyph,
    gate_status_pair,
    gate_status_style,
)
from sase.turns.status import TurnStatusPair

# Bumped only when the JSON payloads below change incompatibly.
GATE_TURN_JSON_SCHEMA_VERSION = 1

_BORDER_STYLE = "#5FAFFF"
_TERMINAL_ROW_STYLE = "dim"
_PENDING_GLYPH = "⋔"
_EMPTY_HINT = (
    "No gate shells here yet. Create one from an agent with:\n\n"
    "  sase gate create --shell -- < gate-request.json\n\n"
    "Then follow it with `sase gate show <id>`."
)
#: Marks a gate shell whose follow-up did not launch (or launched degraded),
#: mirroring ``sase.main.monitor_render``'s ``_FOLLOWUP_ERROR_GLYPH``.
_FOLLOWUP_ERROR_GLYPH = "⚑"
_FOLLOWUP_ERROR_STYLE = "bold yellow"


def _record_status_pair(record: GateTurnRecord) -> TurnStatusPair:
    return gate_status_pair(record.start_status, record.stop_status)


def _effective_label(record: GateTurnRecord) -> str:
    return effective_gate_status(
        _record_status_pair(record),
        gate_state=record.gate_state,
        settled=record.is_terminal,
    )


def _label_glyph(record: GateTurnRecord) -> str:
    glyph = gate_status_glyph(record.gate_state)
    if glyph:
        return glyph
    return _PENDING_GLYPH


def _state_cell(record: GateTurnRecord) -> Text:
    pair = _record_status_pair(record)
    style = gate_status_style(pair, gate_state=record.gate_state, accent=record.accent)
    text = Text(f"{_label_glyph(record)} {_effective_label(record)}", style=style)
    if gate_turn_followup_needs_attention(record):
        text.append(f" {_FOLLOWUP_ERROR_GLYPH}", style=_FOLLOWUP_ERROR_STYLE)
    return text


def _parse_started(timestamp: str) -> datetime | None:
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def _duration_label(record: GateTurnRecord) -> str:
    from sase.ace.hooks.timestamps import format_duration

    started = _parse_started(record.timestamp)
    if started is None:
        return "—"
    now = datetime.now(get_timezone())
    return format_duration(max(0.0, (now - started).total_seconds()))


def _relative_start(record: GateTurnRecord) -> str:
    from sase.notifications.models import format_relative_time

    started = _parse_started(record.timestamp)
    if started is None:
        return record.timestamp
    return format_relative_time(started.isoformat())


def _claim_cell(record: GateTurnRecord) -> Text:
    """Flag a pending gate shell still holding a workspace claim (R2)."""
    if record.is_terminal or record.workspace_policy != "inherit":
        return Text("—", style="dim")
    return Text("workspace", style="bold yellow")


def gate_turn_list_json(
    records: Sequence[GateTurnRecord],
    *,
    scope: dict[str, Any],
) -> dict[str, Any]:
    """Return the stable ``sase gate list`` JSON envelope."""
    return {
        "schema_version": GATE_TURN_JSON_SCHEMA_VERSION,
        "count": len(records),
        "scope": scope,
        "gate_turns": [gate_turn_runtime_json(record) for record in records],
    }


def gate_turn_cancel_json(record: GateTurnRecord, *, changed: bool) -> dict[str, Any]:
    """Return the stable ``sase gate cancel`` JSON envelope."""
    return {
        "schema_version": GATE_TURN_JSON_SCHEMA_VERSION,
        "changed": changed,
        "gate_turn": gate_turn_runtime_json(record),
    }


def gate_turn_table(records: Sequence[GateTurnRecord], *, title: str) -> Panel:
    """Render gate turns as the newest-first table panel."""
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("STATE", no_wrap=True)
    table.add_column("ID", no_wrap=True)
    table.add_column("LABEL", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("AGENT/MEMBER", overflow="ellipsis", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("CLAIM", no_wrap=True)
    table.add_column("ELAPSED", justify="right", no_wrap=True)
    table.add_column("OPENED", justify="right", no_wrap=True)

    for record in records:
        row_style = _TERMINAL_ROW_STYLE if record.is_terminal else ""
        table.add_row(
            _state_cell(record),
            Text(short_gate_turn_id(record.gate_id), style=row_style or "bold"),
            Text(record.label, style=row_style),
            Text(f"{record.lane}/{record.member_agent_name}", style=row_style or "dim"),
            Text(record.kind, style=row_style or "dim"),
            _claim_cell(record),
            Text(_duration_label(record), style=row_style or "dim"),
            Text(_relative_start(record), style=row_style or "dim"),
        )

    return Panel(
        table,
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def empty_gate_turn_panel(title: str, *, hint: str | None = None) -> Panel:
    """Render the friendly empty state that names ``sase gate create --shell``."""
    body = Text(_EMPTY_HINT, style="dim")
    if hint:
        body.append(f"\n\n{hint}", style="#FFD700")
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def gate_turn_list_markdown(records: Sequence[GateTurnRecord]) -> str:
    """Render gate turns as a plain markdown table."""
    if not records:
        return "_No gate shells._\n"
    header = "| State | Id | Label | Agent/Member | Kind | Claim | Elapsed | Opened |"
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [header, divider]
    for record in records:
        state = _effective_label(record)
        if gate_turn_followup_needs_attention(record):
            state = f"{state} {_FOLLOWUP_ERROR_GLYPH}"
        claim = "workspace" if _claim_cell(record).plain == "workspace" else "—"
        rows.append(
            "| {state} | {id} | {label} | {member} | {kind} | {claim} | {elapsed} | "
            "{opened} |".format(
                state=state,
                id=short_gate_turn_id(record.gate_id),
                label=record.label,
                member=f"{record.lane}/{record.member_agent_name}",
                kind=record.kind,
                claim=claim,
                elapsed=_duration_label(record),
                opened=_relative_start(record),
            )
        )
    return "\n".join(rows) + "\n"


__all__ = [
    "GATE_TURN_JSON_SCHEMA_VERSION",
    "empty_gate_turn_panel",
    "gate_turn_cancel_json",
    "gate_turn_list_json",
    "gate_turn_list_markdown",
    "gate_turn_table",
]
