"""Shared helpers for tools panel tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.widgets.tools_panel import AgentToolsPanel


def _entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-05-14T14:00:00+00:00",
        "runtime": "claude",
        "event": "PostToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "toolu_1",
        "duration_ms": 1234,
        "tool_input_summary": {"command": "pytest tests/ace/tui/tools"},
        "tool_response_summary": {"exit_code": 0, "stdout_preview": "ok"},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def _build_panel() -> AgentToolsPanel:
    panel = AgentToolsPanel.__new__(AgentToolsPanel)
    panel._current_agent = None
    panel._current_worker = None
    panel._has_displayed_content = True
    panel._last_entries = None
    panel._last_rows = None
    panel._last_fetch_time = None
    panel._is_background_refreshing = False
    panel.update = MagicMock()  # type: ignore[method-assign]
    panel.post_message = MagicMock()  # type: ignore[method-assign]
    panel.run_worker = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(is_running=False)
    )
    return panel
