"""Handler implementation for the ``sase tool`` CLI group."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.config.tools import (
    ToolCatalog,
    ToolCatalogError,
    load_project_tool_catalog,
)
from sase.core.tool_run import tool_run_summary
from sase.tool.control import (
    ToolStopCliRequest,
    ToolWaitCliRequest,
    handle_stop,
    handle_wait,
)
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.failures import ToolFailuresCliRequest, handle_failures
from sase.tool.query import (
    ToolRunsCliRequest,
    ToolShowCliRequest,
    handle_runs,
    handle_show,
)
from sase.tool.receipt_query import ToolReceiptCliRequest, handle_receipt
from sase.tool.render import EMPTY, format_state, format_typical


_HUMAN_SILENT_DIAGNOSTICS = frozenset({"tool run store does not exist"})


def handle_tool_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase tool ...`` command."""

    subcommand = getattr(args, "tool_subcommand", None)
    if subcommand == "list":
        sys.exit(_handle_list(args))
    if subcommand == "_adopt":
        from sase.tool.adopt import execute_adopted_run

        sys.exit(execute_adopted_run(str(getattr(args, "adopt_run_id", "") or "")))
    if subcommand == "_triage-stage":
        from sase.tool.triage_stage import execute_triage_stage

        sys.exit(
            execute_triage_stage(
                str(getattr(args, "triage_stage_run_id", "") or ""),
                stage_id=str(getattr(args, "triage_stage_id", "") or ""),
                description=str(getattr(args, "triage_stage_description", "") or ""),
                output=getattr(args, "triage_stage_output", None),
            )
        )
    if subcommand == "run":
        tail_raw = getattr(args, "tail_lines", None)
        sys.exit(
            execute_tool_run(
                ToolRunCliRequest(
                    quiet=bool(getattr(args, "quiet", False)),
                    verbose=bool(getattr(args, "verbose", False)),
                    tail_lines=int(tail_raw) if tail_raw is not None else 200,
                    words=tuple(
                        str(part)
                        for part in (getattr(args, "tool_run_words", None) or ())
                    ),
                    hand_off=bool(getattr(args, "hand_off", False)),
                    tail_lines_explicit=tail_raw is not None,
                    keep_going=bool(getattr(args, "keep_going", False)),
                    fail_fast=bool(getattr(args, "fail_fast", False)),
                )
            )
        )
    if subcommand == "failures":
        sys.exit(
            handle_failures(
                ToolFailuresCliRequest(
                    include_all=bool(getattr(args, "tool_failures_all", False)),
                    class_name=getattr(args, "tool_failures_class", None),
                    days=int(getattr(args, "tool_failures_days", 7)),
                    json=bool(getattr(args, "tool_failures_json", False)),
                    limit=int(getattr(args, "tool_failures_limit", 50)),
                    tool=getattr(args, "tool_failures_tool", None),
                )
            )
        )
    if subcommand == "receipt":
        sys.exit(
            handle_receipt(
                ToolReceiptCliRequest(
                    tool=str(getattr(args, "tool_receipt_tool", "") or ""),
                    accept=str(getattr(args, "tool_receipt_accept", "pass")),
                    json=bool(getattr(args, "tool_receipt_json", False)),
                )
            )
        )
    if subcommand == "runs":
        sys.exit(
            handle_runs(
                ToolRunsCliRequest(
                    include_all=bool(getattr(args, "tool_runs_all", False)),
                    agent=getattr(args, "tool_runs_agent", None),
                    cursor=getattr(args, "tool_runs_cursor", None),
                    json=bool(getattr(args, "tool_runs_json", False)),
                    limit=int(getattr(args, "tool_runs_limit", 50)),
                    state=getattr(args, "tool_runs_state", None),
                    tool=getattr(args, "tool_runs_tool", None),
                )
            )
        )
    if subcommand == "show":
        sys.exit(
            handle_show(
                ToolShowCliRequest(
                    run_id=str(getattr(args, "tool_show_run_id", "") or ""),
                    json=bool(getattr(args, "tool_show_json", False)),
                    logs=bool(getattr(args, "tool_show_logs", False)),
                    follow=bool(getattr(args, "tool_show_follow", False)),
                )
            )
        )
    if subcommand == "stop":
        sys.exit(
            handle_stop(
                ToolStopCliRequest(
                    run_id=str(getattr(args, "tool_stop_run_id", "") or ""),
                    json=bool(getattr(args, "tool_stop_json", False)),
                )
            )
        )
    if subcommand == "wait":
        sys.exit(
            handle_wait(
                ToolWaitCliRequest(
                    run_id=str(getattr(args, "tool_wait_run_id", "") or ""),
                    json=bool(getattr(args, "tool_wait_json", False)),
                    tail_lines=getattr(args, "tool_wait_tail_lines", None),
                    timeout_raw=getattr(args, "tool_wait_timeout", None),
                )
            )
        )
    print(
        "Usage: sase tool {failures,list,receipt,run,runs,show,stop,wait}",
        file=sys.stderr,
    )
    sys.exit(2)


def _handle_list(args: argparse.Namespace) -> int:
    try:
        reconcile_unsettled_tool_runs()
        catalog = load_project_tool_catalog()
        envelope = _list_envelope(catalog)
    except ToolCatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - query/store failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_catalog_table(envelope)
    for diagnostic in envelope.get("diagnostics") or ():
        if diagnostic in _HUMAN_SILENT_DIAGNOSTICS:
            continue
        print(diagnostic, file=sys.stderr)
    return 0


def _list_envelope(catalog: ToolCatalog) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    diagnostics = list(catalog.diagnostics)
    for entry in catalog.entries:
        summary = tool_run_summary(
            {
                "schema_version": 1,
                "project": catalog.project,
                "tool_name": entry.name,
                "definition_digest": entry.digest,
            }
        )
        last = summary.get("last")
        typical_ms = summary.get("typical_duration_ms")
        sample_count = int(summary.get("typical_sample_count") or 0)
        tools.append(
            {
                "name": entry.name,
                "description": entry.definition.get("description") or "",
                "argv": list(entry.definition.get("argv") or ()),
                "stages": entry.definition.get("stages") or "none",
                "args": entry.definition.get("args") or "deny",
                "inputs": list(entry.definition.get("inputs") or ()),
                "env": list(entry.definition.get("env") or ()),
                "fingerprint": dict(entry.definition.get("fingerprint") or {}),
                "digest": entry.digest,
                "last": last,
                "typical_duration_ms": typical_ms,
                "typical_sample_count": sample_count,
                "typical_status_breakdown": dict(
                    summary.get("typical_status_breakdown") or {}
                ),
                "diagnostics": [
                    *entry.diagnostics,
                    *(str(item) for item in summary.get("diagnostics") or ()),
                ],
            }
        )
        diagnostics.extend(str(item) for item in summary.get("diagnostics") or ())
    unique_diagnostics = list(dict.fromkeys(diagnostics))
    return {
        "schema_version": 1,
        "project": catalog.project,
        "path": catalog.path,
        "tools": tools,
        "diagnostics": unique_diagnostics,
    }


def _print_catalog_table(envelope: dict[str, Any]) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("NAME")
    table.add_column("LAST")
    table.add_column("TYPICAL")
    table.add_column("DESCRIPTION")
    tools = envelope.get("tools") or ()
    if not tools:
        table.add_row(EMPTY, EMPTY, EMPTY, "no named tools in this project")
    for tool in tools:
        table.add_row(
            str(tool.get("name") or EMPTY),
            format_state(tool.get("last")),
            format_typical(
                tool.get("typical_duration_ms"),
                int(tool.get("typical_sample_count") or 0),
            ),
            str(tool.get("description") or EMPTY),
        )
    console.print(table)


__all__ = ["handle_tool_command"]
