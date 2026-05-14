from __future__ import annotations

from datetime import datetime

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.widgets.tools_panel import (
    _build_tools_timeline_markdown,
    _build_tools_timeline_text,
)


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


def test_tools_timeline_distinguishes_missing_empty_and_present() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    missing = _build_tools_timeline_text(None, fetch_time).plain
    empty = _build_tools_timeline_text([], fetch_time).plain
    present = _build_tools_timeline_text([_entry()], fetch_time).plain

    assert "No tools artifact available" in missing
    assert "No tool calls recorded" in empty
    assert "TOOLS" in present
    assert "Bash" in present
    assert "pytest tests/ace/tui/tools" in present
    assert "1.2s" in present


def test_tools_timeline_markdown_is_exportable() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_markdown(
        [
            _entry(
                status="failure",
                tool_response_summary={"exit_code": 1, "stderr_preview": "boom"},
            )
        ],
        fetch_time,
    )

    assert rendered is not None
    assert rendered.startswith("TOOLS")
    assert "fail | Bash" in rendered
    assert "boom" in rendered
