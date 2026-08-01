"""Shared hint registration for deferred slow tool-call reports."""

from __future__ import annotations

from collections.abc import Iterable

from rich.cells import cell_len

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools.report import (
    SlowToolCallReportSpec,
    tool_call_report_path,
)

from ._agent_display_state import HeaderHintState


def tool_call_report_hint_marker_width(
    entries: Iterable[ToolCallEntry],
    hint_state: HeaderHintState | None,
) -> int:
    """Return the cell width needed for report hint markers in a row group."""
    if hint_state is None:
        return 0
    report_count = sum(1 for entry in entries if _tool_call_report_hint_eligible(entry))
    if not report_count:
        return 0
    largest_hint = hint_state.hint_counter + report_count - 1
    return cell_len(f"[{largest_hint}]")


def register_tool_call_report_hint(
    entry: ToolCallEntry,
    *,
    hint_state: HeaderHintState | None,
    source_label: str | None,
    agent_name: str | None,
) -> str | None:
    """Register a deferred report write for one reportable tool call."""
    if hint_state is None or not _tool_call_report_hint_eligible(entry):
        return None

    hint_number = hint_state.hint_counter
    hint_state.hint_counter += 1
    report_path = tool_call_report_path(entry)
    hint_state.hint_mappings[hint_number] = report_path
    hint_state.tool_call_reports[report_path] = SlowToolCallReportSpec(
        entry=entry,
        source_label=source_label,
        agent_name=agent_name,
        report_path=report_path,
    )
    return f"[{hint_number}]"


def _tool_call_report_hint_eligible(entry: ToolCallEntry) -> bool:
    """Return whether the existing writer can produce a useful report."""
    return entry.status in {"success", "failure"}
