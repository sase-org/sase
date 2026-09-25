"""``sase tool failures`` presentation over the Rust aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sys
import time
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.config.tools import tool_project_identity
from sase.core.tool_run import tool_run_failures
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.render import EMPTY

_CLASSES = ("new", "known", "flaky", "unknown")
_MAX_LIMIT = 1000


class _FailuresQueryError(ValueError):
    """User-facing failures usage error (exit 2)."""


@dataclass(frozen=True)
class ToolFailuresCliRequest:
    include_all: bool
    class_name: str | None
    days: int
    json: bool
    limit: int
    tool: str | None


def handle_failures(request: ToolFailuresCliRequest) -> int:
    """Render ``sase tool failures`` from stored triage signatures."""

    try:
        limit = _validate_limit(request.limit)
        days = _validate_days(request.days)
        class_name = _validate_class(request.class_name)
    except _FailuresQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "days": days,
        "limit": limit,
        "now_ts": int(time.time()),
    }
    if class_name:
        payload["class"] = class_name
    if request.tool:
        payload["tool"] = request.tool
    if request.include_all:
        payload["all_projects"] = True
    else:
        payload["project"] = tool_project_identity()
    try:
        envelope = tool_run_failures(payload)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    groups = [
        group for group in envelope.get("groups") or () if isinstance(group, dict)
    ]
    if not groups:
        print("no recorded failures")
    else:
        _print_failures_table(groups)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _print_failures_table(groups: list[dict[str, Any]]) -> None:
    console = Console(width=120, highlight=False)
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("CLASS", no_wrap=True)
    table.add_column("TOOL/STAGE", no_wrap=True)
    table.add_column("SIGNATURE", overflow="fold")
    table.add_column("RUNS")
    table.add_column("AGENTS")
    table.add_column("FIRST")
    table.add_column("LAST")
    table.add_column("OWNER")
    for group in groups:
        table.add_row(
            _format_class(group.get("newest_class")),
            _format_tool_stage(group),
            str(group.get("display") or group.get("signature") or EMPTY),
            _format_count(group.get("runs")),
            _format_count(group.get("agents")),
            _format_ts(group.get("first_seen_ts")),
            _format_ts(group.get("last_seen_ts")),
            _format_owner(group.get("newest_owners")),
        )
    console.print(table)


def _format_class(value: object) -> str:
    name = str(value or "").strip()
    return name.upper() if name else EMPTY


def _format_tool_stage(group: dict[str, Any]) -> str:
    tool = str(group.get("tool") or EMPTY)
    stage = str(group.get("stage_key") or EMPTY)
    return f"{tool} / {stage}"


def _format_count(value: object) -> str:
    return str(value) if type(value) is int else EMPTY


def _format_ts(value: object) -> str:
    if type(value) is not int:
        return EMPTY
    return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d %H:%M")


def _format_owner(value: object) -> str:
    if not isinstance(value, list) or not value:
        return EMPTY
    first = value[0]
    if isinstance(first, dict):
        owner = str(first.get("id") or "").strip()
        return owner or EMPTY
    return EMPTY


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > _MAX_LIMIT:
        raise _FailuresQueryError(f"-n/--limit must be 1..={_MAX_LIMIT}")
    return limit


def _validate_days(days: int) -> int:
    if days < 0:
        raise _FailuresQueryError("-d/--days must be >= 0")
    return days


def _validate_class(class_name: str | None) -> str | None:
    if class_name is None:
        return None
    if class_name not in _CLASSES:
        allowed = ", ".join(_CLASSES)
        raise _FailuresQueryError(
            f"unknown class {class_name!r}; expected one of {allowed}"
        )
    return class_name


__all__ = ["ToolFailuresCliRequest", "handle_failures"]
