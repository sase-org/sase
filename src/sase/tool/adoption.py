"""Read-only ToolRun adoption report over normalized LLM-call artifacts.

Python discovers ``tool_calls.jsonl`` files and projects their rows; Rust owns
pairing, shell-launch classification, and aggregation (``tool_adoption_report``).
The report never writes: it reads artifacts, the ToolRun ledger, and recording
counters, and it never adds independently measured ToolRun durations to the
overlapping LLM-call durations.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.tool_adoption import tool_adoption_report
from sase.core.tool_run import tool_run_list, tool_run_store_path

_SCHEMA_VERSION = 1
_TOOL_CALLS_FILENAME = "tool_calls.jsonl"
_DEFAULT_DAYS = 7
_LEDGER_PAGE_LIMIT = 1000
_MAX_LEDGER_PAGES = 20
_SHARD_RE = re.compile(r"^\d{6}$")
_DAY_RE = re.compile(r"^\d{2}$")
_STAMP_RE = re.compile(r"^\d{14}$")
# Directory names carry local wall-clock stamps; a day of slack absorbs any
# UTC offset while file mtimes make the exact cut.
_DISCOVERY_MARGIN = timedelta(days=1)
_I64_MAX = 2**63 - 1


def _subdirs(path: Path) -> Iterator[os.DirEntry[str]]:
    try:
        with os.scandir(path) as entries:
            found = [entry for entry in entries if entry.is_dir(follow_symlinks=False)]
    except OSError:
        return
    yield from sorted(found, key=lambda entry: entry.name)


def _workflow_candidates(workflow: Path, floor: datetime) -> Iterator[Path]:
    for entry in _subdirs(workflow):
        name = entry.name
        if _SHARD_RE.match(name):
            year, month = int(name[:4]), int(name[4:])
            if (year, month) < (floor.year, floor.month):
                continue
            for day in _subdirs(Path(entry.path)):
                if not _DAY_RE.match(day.name):
                    continue
                try:
                    day_start = datetime(year, month, int(day.name))
                except ValueError:
                    continue
                if day_start.date() < floor.date():
                    continue
                for stamp in _subdirs(Path(day.path)):
                    yield Path(stamp.path) / _TOOL_CALLS_FILENAME
        elif _STAMP_RE.match(name):
            try:
                stamped = datetime.strptime(name, "%Y%m%d%H%M%S")
            except ValueError:
                continue
            if stamped >= floor:
                yield Path(entry.path) / _TOOL_CALLS_FILENAME


def _discover_tool_call_files(projects_dir: Path, since: datetime) -> list[Path]:
    """Return ``tool_calls.jsonl`` files that may hold rows newer than *since*."""

    floor = since.astimezone(UTC).replace(tzinfo=None) - _DISCOVERY_MARGIN
    since_ts = since.timestamp()
    found: list[Path] = []
    for project in _subdirs(projects_dir):
        for workflow in _subdirs(Path(project.path) / "artifacts"):
            for path in _workflow_candidates(Path(workflow.path), floor):
                try:
                    if path.stat().st_mtime >= since_ts:
                        found.append(path)
                except OSError:
                    continue
    return sorted(found)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        value = int(value) if math.isfinite(value) else None
    if isinstance(value, int) and abs(value) <= _I64_MAX:
        return value
    return None


def _project_row(record: object) -> dict[str, Any] | None:
    """Project one JSONL record onto the fields the Rust report needs."""

    if not isinstance(record, Mapping):
        return None
    event = _optional_str(record.get("event"))
    if event is None:
        return None
    summary = record.get("tool_input_summary")
    command = summary.get("command") if isinstance(summary, Mapping) else None
    row: dict[str, Any] = {
        "event": event,
        "recorded_at": _optional_str(record.get("recorded_at")),
        "completed_at": _optional_str(record.get("completed_at")),
        "runtime": _optional_str(record.get("runtime")),
        "tool_name": _optional_str(record.get("tool_name")),
        "tool_use_id": _optional_str(record.get("tool_use_id")),
        "duration_ms": _optional_int(record.get("duration_ms")),
        "command": command if isinstance(command, str) else None,
    }
    return {key: value for key, value in row.items() if value is not None}


def _read_rows(path: Path) -> tuple[list[dict[str, Any]], int] | None:
    """Return ``(rows, malformed_row_count)``, or ``None`` when unreadable."""

    rows: list[dict[str, Any]] = []
    malformed = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = _project_row(json.loads(text))
                except ValueError:
                    row = None
                if row is None:
                    malformed += 1
                else:
                    rows.append(row)
    except OSError:
        return None
    return rows, malformed


def _catalog_wire(catalog: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": entry.name,
            "argv": [str(word) for word in entry.definition.get("argv") or ()],
            "args": str(entry.definition.get("args") or "deny"),
        }
        for entry in catalog.entries
    ]


def _ledger_coverage(since_ts: int) -> dict[str, Any]:
    """Count native ToolRuns in the window without reconciling or writing."""

    if not tool_run_store_path().is_file():
        return {"available": False, "reason": "no ToolRun ledger on this machine yet"}
    by_tool: dict[str, int] = {}
    by_state: dict[str, int] = {}
    total = 0
    cursor: str | None = None
    exhausted = False
    try:
        for _ in range(_MAX_LEDGER_PAGES):
            request: dict[str, Any] = {"limit": _LEDGER_PAGE_LIMIT}
            if cursor:
                request["cursor"] = cursor
            page = tool_run_list(request)
            reached_window_start = False
            for run in page.get("runs") or ():
                if int(run.get("created_ts") or 0) < since_ts:
                    reached_window_start = True
                    continue
                if run.get("source") != "native":
                    continue
                total += 1
                name = str(run.get("tool_name") or "(ad hoc)")
                by_tool[name] = by_tool.get(name, 0) + 1
                state = str(run.get("state") or "unknown")
                by_state[state] = by_state.get(state, 0) + 1
            cursor = page.get("next_cursor")
            if reached_window_start or not cursor:
                exhausted = True
                break
    except Exception as exc:  # noqa: BLE001 - coverage is best effort; the report stays useful.
        return {"available": False, "reason": f"ledger query failed: {exc}"}
    return {
        "available": True,
        "runs": total,
        "by_tool": dict(sorted(by_tool.items())),
        "by_state": dict(sorted(by_state.items())),
        "complete": exhausted,
    }


def _counter_totals(
    series: Sequence[Mapping[str, Any]], label: str
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in series:
        labels = item.get("labels") or {}
        key = str(labels.get(label) or "unlabeled")
        values = [
            float(point[1])
            for point in item.get("points") or ()
            if isinstance(point, Sequence) and len(point) >= 2 and point[1] is not None
        ]
        totals[key] = totals.get(key, 0.0) + sum(values)
    return {key: totals[key] for key in sorted(totals)}


def _recording_signals(since_ts: int, until_ts: int) -> dict[str, Any]:
    """Read recording attempt/error counters from the local telemetry store."""

    try:
        from sase.telemetry.query import query_range

        span = max(1, until_ts - since_ts)
        attempts = query_range(
            "sase_tool_run_attempts_total",
            start_ts=since_ts,
            end_ts=until_ts,
            step_seconds=span,
            kind="counter",
            group_by=["result"],
        )
        errors = query_range(
            "sase_tool_run_recording_errors_total",
            start_ts=since_ts,
            end_ts=until_ts,
            step_seconds=span,
            kind="counter",
            group_by=["op"],
        )
    except Exception as exc:  # noqa: BLE001 - telemetry may be disabled or unavailable.
        return {"available": False, "reason": f"telemetry query failed: {exc}"}
    return {
        "available": True,
        "attempts": _counter_totals(attempts.get("series") or (), "result"),
        "errors": _counter_totals(errors.get("series") or (), "op"),
    }


def _collect_report(
    days: int,
    *,
    now: datetime | None = None,
    catalog: Any = None,
    projects_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the full versioned adoption report for the last *days* days."""

    if catalog is None:
        from sase.config.tools import load_project_tool_catalog

        catalog = load_project_tool_catalog()
    end = (now or datetime.now(UTC)).astimezone(UTC)
    start = end - timedelta(days=days)
    diagnostics: list[str] = list(catalog.diagnostics)
    if not catalog.entries:
        diagnostics.append(
            "the current project declares no tools: catalog; no command can be "
            "classified"
        )

    files: list[dict[str, Any]] = []
    unreadable = 0
    malformed_rows = 0
    paths = _discover_tool_call_files(projects_dir or sase_projects_dir(), start)
    for path in paths:
        result = _read_rows(path)
        if result is None:
            unreadable += 1
            continue
        rows, malformed = result
        malformed_rows += malformed
        files.append({"file_id": str(path), "records": rows})

    calls = tool_adoption_report(
        {
            "schema_version": 1,
            "tools": _catalog_wire(catalog),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "files": files,
        }
    )
    # File ids are local paths; the report only needs the counts.
    diagnostics.extend(str(item) for item in calls.get("diagnostics") or ())
    return {
        "schema_version": _SCHEMA_VERSION,
        "window": {
            "days": days,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "catalog": {
            "project": catalog.project,
            "tools": [entry.name for entry in catalog.entries],
        },
        "discovery": {
            "files_found": len(paths),
            "files_read": len(files),
            "files_unreadable": unreadable,
            "malformed_rows": malformed_rows,
        },
        "calls": calls,
        "ledger": _ledger_coverage(int(start.timestamp())),
        "recording": _recording_signals(int(start.timestamp()), int(end.timestamp())),
        "caveats": [
            "Wall shares use LLM-call durations only; ToolRun ledger durations "
            "overlap them and are never added.",
            "An outer `sase monitor start` call is counted separately; its own "
            "duration is not the detached child's runtime.",
            "Commands that cannot be unwrapped conservatively (pipelines, "
            "multi-command scripts) are ambiguous, not attributed.",
            "Ledger run counts and recording errors are separate coverage "
            "signals, not inputs to the shares.",
        ],
        "diagnostics": diagnostics,
    }


def _format_ms(value: int) -> str:
    seconds = value // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _format_share(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _render_headline(calls: Mapping[str, Any]) -> list[str]:
    headline = calls.get("headline")
    if not headline:
        return ["Headline: unavailable (headline tool is not in the catalog)"]
    tool = headline["tool"]
    threshold = _format_ms(int(headline["heavy_threshold_ms"]))
    share = headline["wrapped_heavy_wall_share"]
    lines = [
        f"Headline: wrapped heavy `{tool}` wall share (heavy = at least {threshold})",
        f"  {_format_share(share)}"
        + (
            ""
            if share is not None
            else "  (no classifiable heavy calls in the window; denominator is 0)"
        ),
        "  wrapped "
        f"{_format_ms(int(headline['wrapped_heavy_wall_ms']))} "
        f"({headline['wrapped_heavy_count']} calls) / classifiable "
        f"{_format_ms(int(headline['denominator_ms']))} "
        f"(wrapped + {headline['raw_heavy_count']} raw calls "
        f"{_format_ms(int(headline['raw_heavy_wall_ms']))})",
        "  not in the denominator: "
        f"{headline['ambiguous_heavy_count']} ambiguous heavy calls "
        f"({_format_ms(int(headline['ambiguous_heavy_wall_ms']))}), "
        f"{headline['monitor_starts']} outer monitor starts",
    ]
    return lines


def _render_tools(calls: Mapping[str, Any]) -> list[str]:
    tools = calls.get("tools") or []
    if not tools:
        return []
    header = (
        f"{'TOOL':<14}{'WRAPPED':>8}{'RAW':>6}{'AMBIG':>7}{'MON':>5}"
        f"{'SHARE(n)':>10}{'SHARE(wall)':>13}{'SHARE(heavy)':>14}"
    )
    lines = ["", header]
    for tool in tools:
        shares = tool["shares"]
        lines.append(
            f"{tool['tool']:<14}{tool['wrapped']['count']:>8}{tool['raw']['count']:>6}"
            f"{tool['ambiguous']['count']:>7}{tool['monitor_starts']:>5}"
            f"{_format_share(shares['wrapped_count_share']):>10}"
            f"{_format_share(shares['wrapped_wall_share']):>13}"
            f"{_format_share(shares['wrapped_heavy_wall_share']):>14}"
        )
    return lines


def _render_ledger(report: Mapping[str, Any]) -> list[str]:
    ledger = report["ledger"]
    lines = [""]
    if ledger["available"]:
        by_tool = ", ".join(
            f"{name}={count}" for name, count in ledger["by_tool"].items()
        )
        suffix = "" if ledger["complete"] else " (page limit reached; count is a floor)"
        lines.append(
            f"Ledger: {ledger['runs']} native ToolRuns in the window"
            + (f" ({by_tool})" if by_tool else "")
            + suffix
        )
    else:
        lines.append(f"Ledger: unavailable ({ledger['reason']})")
    recording = report["recording"]
    if recording["available"]:
        attempts = ", ".join(f"{k}={v:g}" for k, v in recording["attempts"].items())
        errors = ", ".join(f"{k}={v:g}" for k, v in recording["errors"].items())
        lines.append(f"Recording attempts: {attempts or 'none observed'}")
        lines.append(f"Recording errors: {errors or 'none observed'}")
    else:
        lines.append(f"Recording signals: unavailable ({recording['reason']})")
    return lines


def _render_text(report: Mapping[str, Any]) -> str:
    calls = report["calls"]
    discovery = report["discovery"]
    records = calls["records"]
    exclusions = calls["exclusions"]
    window = report["window"]
    lines = [
        f"ToolRun adoption report: last {window['days']} days",
        f"window   {window['start']} -> {window['end']}",
        f"sources  {discovery['files_read']} of {discovery['files_found']} "
        f"LLM-call files read ({discovery['files_unreadable']} unreadable, "
        f"{discovery['malformed_rows']} malformed rows), {records['rows']} rows",
        f"calls    {records['shell_calls']} shell calls "
        f"({records['non_shell_calls']} non-shell)",
        "",
        *_render_headline(calls),
        *_render_tools(calls),
        "",
        "Exclusions: "
        f"{exclusions['unpaired_uses']} unpaired, "
        f"{exclusions['orphan_results']} orphan results, "
        f"{exclusions['negative_duration']} negative, "
        f"{exclusions['missing_duration']} untimed, "
        f"{exclusions['over_max_duration']} over "
        f"{_format_ms(int(calls['max_duration_ms']))}, "
        f"{exclusions['truncated_commands']} truncated, "
        f"{exclusions['outside_window']} outside window",
        *_render_ledger(report),
    ]
    diagnostics = report["diagnostics"]
    if diagnostics:
        lines += ["", "Diagnostics:", *(f"  {item}" for item in diagnostics)]
    lines += ["", "Caveats:", *(f"  {item}" for item in report["caveats"])]
    return "\n".join(lines)


def _positive_days(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid day count: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("days must be at least 1")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Run the read-only adoption report; returns a process exit code."""

    parser = argparse.ArgumentParser(
        prog="tool_adoption_report",
        description=(
            "Report how often heavy catalog commands (such as `just check`) ran "
            "through `sase tool run` versus raw, from normalized LLM-call "
            "artifacts. Read-only; never imports history into the ledger."
        ),
    )
    parser.add_argument(
        "-d",
        "--days",
        type=_positive_days,
        default=_DEFAULT_DAYS,
        help=f"Window length in days (default: {_DEFAULT_DAYS})",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a versioned machine-readable JSON object",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        report = _collect_report(args.days)
    except Exception as exc:  # noqa: BLE001 - every failure is a nonzero, explained exit.
        print(f"tool_adoption_report: {exc}", file=sys.stderr)
        return 1
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0
