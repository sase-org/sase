from __future__ import annotations

from datetime import datetime

from sase.ace.tui.widgets import tools_panel as tools_panel_mod
from sase.ace.tui.widgets.tools_panel import (
    _build_tools_timeline_markdown,
    _build_tools_timeline_text,
)

from ._tools_panel_helpers import _entry


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


def test_tools_timeline_markdown_exports_codex_compact_targets() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_markdown(
        [
            _entry(
                runtime="codex",
                event="FunctionCall",
                tool_name="Read",
                tool_use_id="call_1",
                duration_ms=None,
                source="stream",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={},
            )
        ],
        fetch_time,
    )

    assert rendered is not None
    assert "ok | Read | src/sase/foo.py" in rendered


def test_tools_timeline_shows_pending_state() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="pending",
                duration_ms=None,
                tool_response_summary={},
            )
        ],
        fetch_time,
    ).plain

    assert "wait" in rendered
    assert "Bash" in rendered


def test_tools_timeline_truncates_long_command() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)
    long_command = "echo " + "x" * 200

    rendered = _build_tools_timeline_text(
        [_entry(tool_input_summary={"command": long_command})],
        fetch_time,
    ).plain

    assert long_command not in rendered
    assert "..." in rendered


def test_tools_timeline_renders_failure_with_error_detail() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="failure",
                tool_response_summary={
                    "exit_code": 2,
                    "stderr_preview": "ENOENT: missing file",
                },
            )
        ],
        fetch_time,
    ).plain

    assert "fail" in rendered
    assert "exit 2" in rendered
    assert "ENOENT: missing file" in rendered


def test_tools_timeline_renders_interrupted_state() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="interrupted",
                duration_ms=None,
                tool_response_summary={"interrupted": True},
            )
        ],
        fetch_time,
    ).plain

    assert "stop" in rendered


def test_tools_timeline_renders_rich_response_detail() -> None:
    """A successful row should surface a stdout/content preview line."""
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                tool_name="Read",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={"content_preview": "class Foo:\n    pass"},
                duration_ms=12,
            )
        ],
        fetch_time,
    ).plain

    assert "Read" in rendered
    assert "src/sase/foo.py" in rendered
    assert "class Foo:" in rendered
    assert "12ms" in rendered


def test_tools_timeline_renders_source_chips_for_root_aggregate() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [_entry(tool_use_id="plan"), _entry(tool_use_id="code")],
        fetch_time,
        rows=(
            tools_panel_mod._ToolTimelineRow(_entry(tool_use_id="plan"), "plan", 0),
            tools_panel_mod._ToolTimelineRow(_entry(tool_use_id="code"), "code", 1),
        ),
    ).plain

    assert "ok     plan" in rendered
    assert "ok     code" in rendered
