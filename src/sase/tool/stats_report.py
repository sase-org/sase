"""``sase tool stats`` readout over the ToolRun ledger.

Turns the ToolRun ledger into routine, read-only readouts: per tool, stage,
route, and provider p50/p90, outcome and censoring mix, ceiling kills and
wasted hours, repeats and duplicates, a daily trend, a chronological backtest,
and host pressure. The report itself is computed by the Rust core
(``sase_core::tool_run::tool_run_stats_report``); this module only validates
CLI arguments and presents the envelope. Human rendering lives in
``sase.tool.stats_report_render``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import platform
import sys
import time
from typing import Any

from sase.config.tools import tool_project_identity
from sase.core.time import get_timezone
from sase.core.tool_run import tool_run_stats_report
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.stats_report_render import print_human


class _StatsQueryError(ValueError):
    """User-facing stats usage error (exit 2)."""


@dataclass(frozen=True)
class ToolStatsCliRequest:
    include_all: bool
    days: int
    json: bool
    tool: str | None


def handle_stats(request: ToolStatsCliRequest) -> int:
    """Render ``sase tool stats``; 0 reported, 1 store failure, 2 usage."""

    try:
        days = _validate_days(request.days)
    except _StatsQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    try:
        envelope = _build_envelope(
            include_all=request.include_all,
            days=days,
            tool=request.tool,
        )
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(f"stats report failed: {exc}", file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    print_human(envelope, detail_tool=request.tool)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _validate_days(days: int) -> int:
    if type(days) is bool or not isinstance(days, int) or not 1 <= days <= 180:
        raise _StatsQueryError("-d/--days must be 1..180")
    return days


def _build_envelope(
    *, include_all: bool, days: int, tool: str | None
) -> dict[str, Any]:
    """Assemble the versioned stats envelope via the Rust core."""

    payload: dict[str, Any] = {
        "days": days,
        "now_ts": int(time.time()),
        "utc_offset_seconds": _local_utc_offset_seconds(),
    }
    if not include_all:
        payload["project"] = tool_project_identity()
    if tool:
        payload["tool_name"] = tool
    envelope = tool_run_stats_report(payload)
    envelope["host"] = platform.node()
    if envelope.get("schema_version") is None:
        envelope["schema_version"] = 1
    return envelope


def _local_utc_offset_seconds() -> int:
    offset = datetime.now(get_timezone()).utcoffset()
    return int(offset.total_seconds()) if offset is not None else 0


__all__ = ["ToolStatsCliRequest", "handle_stats"]
