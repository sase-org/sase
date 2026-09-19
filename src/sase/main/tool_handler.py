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


_EMPTY = "—"
_HUMAN_SILENT_DIAGNOSTICS = frozenset({"tool run store does not exist"})


def handle_tool_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase tool ...`` command."""

    subcommand = getattr(args, "tool_subcommand", None)
    if subcommand == "list":
        sys.exit(_handle_list(args))
    print("Usage: sase tool {list}", file=sys.stderr)
    sys.exit(2)


def _handle_list(args: argparse.Namespace) -> int:
    try:
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
        table.add_row(_EMPTY, _EMPTY, _EMPTY, "no named tools in this project")
    for tool in tools:
        table.add_row(
            str(tool.get("name") or _EMPTY),
            _format_last(tool.get("last")),
            _format_typical(
                tool.get("typical_duration_ms"),
                int(tool.get("typical_sample_count") or 0),
            ),
            str(tool.get("description") or _EMPTY),
        )
    console.print(table)


def _format_last(last: object) -> str:
    if not isinstance(last, dict):
        return _EMPTY
    state = str(last.get("state") or "").strip()
    if not state:
        return _EMPTY
    exit_code = last.get("exit_code")
    if exit_code is not None and state in {"failed", "signaled", "interrupted"}:
        return f"{state}/{exit_code}"
    return state


def _format_typical(duration_ms: object, sample_count: int) -> str:
    if duration_ms is None or sample_count <= 0:
        return _EMPTY
    if type(duration_ms) is not int:
        return _EMPTY
    return f"{_format_duration_ms(duration_ms)} (n={sample_count})"


def _format_duration_ms(duration_ms: int) -> str:
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000
    if seconds < 60:
        if seconds == int(seconds):
            return f"{int(seconds)}s"
        return f"{seconds:.1f}s"
    minutes, rem = divmod(int(seconds), 60)
    if rem == 0:
        return f"{minutes}m"
    return f"{minutes}m {rem}s"


__all__ = ["handle_tool_command"]
