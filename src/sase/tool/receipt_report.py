"""``sase tool receipts`` opportunity report over retained verdict receipts.

Lists retained verdict receipts and measures content-equivalent verification
repeats: how often a named tool re-ran on a content-identical tree. The
comparison is content-addressed — it compares Git blobs by content, not only
HEAD — so a verified dirty tree that is later committed and rechecked at a
new HEAD counts as a repeat opportunity. Toolchain, environment, extra
arguments, and catalog identity stay in the key.

The report informs a later reuse decision; it never changes what ``run``
executes. Every ``sase tool run`` still spawns its child. A measurement
opportunity is not a covering receipt: use ``sase tool receipt TOOL`` to ask
whether the current tree is covered now. Runs whose history is unavailable
(missing Git objects, unresolvable repos, incomplete fingerprints) are
reported as uncomparable, never guessed.

The report itself is computed by the Rust core
(``sase_core::tool_run::tool_run_receipts_report``); this module only
validates CLI arguments and presents the envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.config.tools import tool_project_identity
from sase.content_layout import discover_project_root
from sase.core.tool_run import tool_run_receipts_report
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.render import EMPTY

# Mirrors RECEIPTS_REPORT_MAX_RUNS in the core; used only for the human
# truncation message, never for ledger math.
_MAX_RUNS = 500

_MEASUREMENT_NOTE = (
    "opportunities are measurement only; every `sase tool run` still "
    "executes its child. An opportunity is not a covering receipt: "
    "run `sase tool receipt TOOL` to ask whether the current tree is covered."
)


class _ReceiptsQueryError(ValueError):
    """User-facing receipts usage error (exit 2)."""


@dataclass(frozen=True)
class ToolReceiptsCliRequest:
    days: int
    json: bool


def handle_receipts(request: ToolReceiptsCliRequest) -> int:
    """Render ``sase tool receipts``; 0 reported, 1 store failure, 2 usage."""

    try:
        days = _validate_days(request.days)
    except _ReceiptsQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    project = tool_project_identity()
    now_ts = int(time.time())
    try:
        envelope = _build_envelope(project, days, now_ts)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(f"receipts report failed: {exc}", file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_human(envelope)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _validate_days(days: int) -> int:
    if days < 0:
        raise _ReceiptsQueryError("-d/--days must be >= 0")
    return days


def _build_envelope(project: str, days: int, now_ts: int) -> dict[str, Any]:
    """Assemble the versioned receipts opportunity envelope via the Rust core."""

    found = discover_project_root()
    root = found if found is not None else Path.cwd()
    return tool_run_receipts_report(
        {
            "project": project,
            "days": days,
            "now_ts": now_ts,
            "project_root": str(root),
        }
    )


def _print_human(envelope: dict[str, Any]) -> None:
    console = Console(width=120, highlight=False)
    receipts = envelope.get("receipts") or {}
    items = [item for item in receipts.get("items") or () if isinstance(item, dict)]
    window = envelope.get("window") or {}
    console.print(
        f"receipts for {envelope.get('project')} "
        f"(last {window.get('days')}d): "
        f"{receipts.get('count', 0)} retained "
        f"({receipts.get('active', 0)} active, "
        f"{receipts.get('expired', 0)} expired, "
        f"{receipts.get('superseded', 0)} superseded)"
    )
    if not items:
        print("no recorded receipts")
    else:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("TOOL", no_wrap=True)
        table.add_column("RECEIPT", overflow="fold")
        table.add_column("VERDICT", no_wrap=True)
        table.add_column("AGE", no_wrap=True)
        table.add_column("STATUS", no_wrap=True)
        for item in items:
            status = str(item.get("status") or EMPTY)
            if item.get("expired"):
                status = "expired"
            table.add_row(
                str(item.get("tool") or EMPTY),
                _short_id(item.get("receipt_id")),
                str(item.get("verdict") or EMPTY),
                _format_age(item.get("age_seconds")),
                _format_status(status),
            )
        console.print(table)
    opportunities = envelope.get("opportunities") or {}
    groups = [
        group for group in opportunities.get("groups") or () if isinstance(group, dict)
    ]
    console.print(
        f"content-equivalent repeats: {opportunities.get('group_count', 0)} groups, "
        f"{opportunities.get('repeat_runs', 0)} repeat runs, "
        f"{opportunities.get('repeat_hours', 0)}h summed duration"
    )
    if groups:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("GROUP", no_wrap=True)
        table.add_column("TOOL", no_wrap=True)
        table.add_column("RUNS", no_wrap=True)
        table.add_column("SAVED", no_wrap=True)
        table.add_column("COMMITS", no_wrap=True)
        for group in groups:
            table.add_row(
                str(group.get("group_id") or EMPTY),
                str(group.get("tool") or EMPTY),
                str(group.get("runs") or EMPTY),
                _format_duration_ms(group.get("repeat_duration_ms")),
                "dirty-to-commit" if group.get("spans_commits") else "same HEAD",
            )
        console.print(table)
        top_tools = [
            entry
            for entry in opportunities.get("top_tools") or ()
            if isinstance(entry, dict)
        ]
        for entry in top_tools[:5]:
            console.print(
                f"  {entry.get('tool')}: "
                f"{entry.get('repeat_runs')} repeats, "
                f"{_format_duration_ms(entry.get('repeat_duration_ms'))}"
            )
    else:
        print("no content-equivalent repeats")
    uncomparable = envelope.get("uncomparable") or {}
    if uncomparable.get("count"):
        print(
            f"{uncomparable.get('count')} runs uncomparable"
            + (" (truncated)" if uncomparable.get("truncated") else "")
        )
    if envelope.get("runs_truncated"):
        print(f"run history truncated to the newest {_MAX_RUNS} runs")
    print(_MEASUREMENT_NOTE)


def _short_id(value: object) -> str:
    text = str(value or "").strip()
    return text[:12] if text else EMPTY


def _format_status(status: str) -> str:
    if status == "active":
        return "[green]active[/green]"
    if status == "expired":
        return "[yellow]expired[/yellow]"
    return f"[dim]{status or EMPTY}[/dim]"


def _format_age(age_seconds: object) -> str:
    if type(age_seconds) is bool or not isinstance(age_seconds, (int, float)):
        return EMPTY
    total = max(0, int(age_seconds))
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _format_duration_ms(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    total_ms = max(0, int(value))
    if total_ms < 1000:
        return f"{total_ms}ms"
    total_seconds = total_ms // 1000
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


__all__ = ["ToolReceiptsCliRequest", "handle_receipts"]
