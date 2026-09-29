"""``sase tool runs`` query presentation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.config.tools import tool_project_identity
from sase.core.tool_run import tool_run_list
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.render import (
    EMPTY,
    format_argv,
    format_duration_ms,
    format_state,
    format_tool_name,
)


_RUN_STATES = frozenset(
    {
        "created",
        "failed",
        "interrupted",
        "lost",
        "running",
        "signaled",
        "succeeded",
    }
)
_MAX_LIMIT = 1000


class _ToolRunQueryError(ValueError):
    """User-facing query usage error (exit 2)."""


@dataclass(frozen=True)
class ToolRunsCliRequest:
    include_all: bool
    agent: str | None
    cursor: str | None
    json: bool
    limit: int
    state: str | None
    tool: str | None


def handle_runs(request: ToolRunsCliRequest) -> int:
    """Render ``sase tool runs`` after reconciling unsettled wrappers."""

    try:
        limit = _validate_limit(request.limit)
        state = _validate_state(request.state)
    except _ToolRunQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "limit": limit,
    }
    if request.tool:
        payload["tool"] = request.tool
    if state:
        payload["state"] = state
    if request.agent:
        payload["agent"] = request.agent
    if request.cursor:
        payload["cursor"] = request.cursor
    if not request.include_all:
        payload["project"] = tool_project_identity()
    try:
        envelope = tool_run_list(payload)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_runs_table(envelope)
    cursor = envelope.get("next_cursor")
    if cursor:
        print(f"next_cursor: {cursor}", file=sys.stderr)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _print_runs_table(envelope: dict[str, Any]) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID")
    table.add_column("TOOL")
    table.add_column("STATE")
    table.add_column("DURATION")
    table.add_column("ARGV")
    runs = envelope.get("runs") or ()
    if not runs:
        table.add_row(EMPTY, EMPTY, EMPTY, EMPTY, "no tool runs")
    for run in runs:
        if not isinstance(run, dict):
            continue
        table.add_row(
            str(run.get("run_id") or EMPTY),
            format_tool_name(run),
            _format_runs_state(run),
            format_duration_ms(
                run.get("duration_ms") if type(run.get("duration_ms")) is int else None
            ),
            format_argv(run),
        )
    console.print(table)


def _format_runs_state(run: dict[str, Any]) -> str:
    """Render the STATE cell, marking hand-offs and starting runs."""

    state = format_state(run)
    markers: list[str] = []
    if str(run.get("launch_mode") or "") == "handoff":
        markers.append("handoff")
    if str(run.get("state") or "") == "created":
        markers.append("starting")
    if markers:
        return f"{state} ({', '.join(markers)})"
    return state


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > _MAX_LIMIT:
        raise _ToolRunQueryError(f"-n/--limit must be 1..={_MAX_LIMIT}")
    return limit


def _validate_state(state: str | None) -> str | None:
    if state is None:
        return None
    if state not in _RUN_STATES:
        allowed = ", ".join(sorted(_RUN_STATES))
        raise _ToolRunQueryError(f"unknown state {state!r}; expected one of {allowed}")
    return state


__all__ = [
    "ToolRunsCliRequest",
    "handle_runs",
]
