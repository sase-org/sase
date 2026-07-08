from __future__ import annotations

from datetime import datetime

from sase.ace.tui.widgets import tools_panel as tools_panel_mod
from sase.ace.tui.widgets.tools_panel import (
    ToolDetailLevel,
    _build_tools_timeline_markdown,
    _build_tools_timeline_text,
)

from ._tools_panel_helpers import _build_panel, _entry


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


def test_tools_timeline_shows_incomplete_state() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="incomplete",
                duration_ms=None,
                completed_at="2026-05-14T14:00:45+00:00",
                tool_response_summary={},
            )
        ],
        fetch_time,
    ).plain

    assert "miss" in rendered
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


def test_tools_timeline_renders_subagent_summary_and_expanded_details() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)
    subagent_summary = {
        "agent_type": "Explore",
        "agent_status": "completed",
        "resolved_model": "claude-opus-4-8",
        "total_duration_ms": 114_000,
        "total_tokens": 72_178,
        "total_tool_use_count": 22,
        "tool_stats": {
            "read_count": 18,
            "search_count": 3,
            "bash_count": 1,
            "edit_count": 0,
            "lines_added": 0,
            "lines_removed": 0,
        },
        "content_preview": "Found the failing branch.\nNo code changes needed.",
        "content_full": "Found the failing branch.\nNo code changes needed.",
    }
    entry = _entry(
        tool_name="Agent",
        tool_input_summary={
            "subagent_type": "Explore",
            "description": "Investigate branch",
            "prompt_length": 400,
        },
        tool_response_summary=subagent_summary,
        duration_ms=114_000,
    )

    rendered = _build_tools_timeline_text(
        [entry],
        fetch_time,
        detail_level=ToolDetailLevel.EXPANDED,
    ).plain

    assert "Agent" in rendered
    assert "Investigate branch" in rendered
    assert (
        "Explore | 22 tools | 72k tok | 1m 54s - Found the failing branch." in rendered
    )
    assert "subagent Explore · claude-opus-4-8 · completed · 1m 54s" in rendered
    assert "72,178 tokens · 22 tool uses" in rendered
    assert "18 reads · 3 searches · 1 bash · 0 edits · +0 / -0 lines" in rendered
    assert "final message" in rendered
    assert "No code changes needed." in rendered

    markdown = _build_tools_timeline_markdown(
        [entry],
        fetch_time,
        detail_level=ToolDetailLevel.EXPANDED,
    )

    assert markdown is not None
    assert "subagent: Explore · claude-opus-4-8 · completed · 1m 54s" in markdown
    assert "final message:" in markdown


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


def test_tools_timeline_expanded_surfaces_full_details() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)
    long_command = "python - <<'PY'\n" + "print('expanded detail')\n" * 2 + "PY"
    stdout = "\n".join(f"out {index}" for index in range(8))

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="failure",
                tool_input_summary={
                    "command": long_command,
                    "timeout": 30,
                    "description": "runs diagnostics",
                },
                tool_response_summary={
                    "exit_code": 2,
                    "success": False,
                    "stdout_preview": stdout,
                    "stderr_preview": "boom\nbad",
                },
                error="line one\nline two",
            )
        ],
        fetch_time,
        detail_level=ToolDetailLevel.EXPANDED,
    ).plain

    assert "detail: expanded" in rendered
    assert "python - <<'PY'" in rendered
    assert "print('expanded detail')" in rendered
    assert "timeout 30" in rendered
    assert "response exit 2 · failed" in rendered
    assert "stdout" in rendered
    assert "... (+2 more lines)" in rendered
    assert "stderr" in rendered
    assert "line two" in rendered


def test_tools_timeline_full_surfaces_provenance() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                completed_at="2026-05-14T14:00:03+00:00",
                source="hook",
                cwd="/repo/sase",
                permission_mode="acceptEdits",
                agent_type="run",
                session_id="session-abcdef123456",
                source_path="/artifacts/tool_calls.jsonl",
                line_number=7,
            )
        ],
        fetch_time,
        detail_level=ToolDetailLevel.FULL,
    ).plain

    assert "detail: full" in rendered
    assert "meta completed" in rendered
    assert "claude/hook" in rendered
    assert "mode acceptEdits" in rendered
    assert "cwd /repo/sase" in rendered
    assert "session session-abcd" in rendered
    assert "/artifacts/tool_calls.jsonl:7" in rendered


def test_tools_timeline_markdown_matches_detail_level() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_markdown(
        [
            _entry(
                tool_input_summary={"command": "echo " + "x" * 120, "timeout": 5},
                tool_response_summary={"stdout_preview": "ok"},
                source_path="/artifacts/tool_calls.jsonl",
                line_number=9,
            )
        ],
        fetch_time,
        detail_level=ToolDetailLevel.FULL,
    )

    assert rendered is not None
    assert "detail: full" in rendered
    assert "command:" in rendered
    assert "timeout: 5" in rendered
    assert "stdout:" in rendered
    assert "meta:" in rendered


def test_tools_panel_detail_level_rerenders_cached_rows() -> None:
    panel = _build_panel()
    panel._last_entries = (_entry(tool_input_summary={"command": "echo " + "x" * 120}),)
    panel._last_fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    assert panel.expand_detail() is True
    assert panel.detail_level == ToolDetailLevel.EXPANDED
    assert panel.update.called
    rendered = panel.update.call_args.args[0].plain
    assert "detail: expanded" in rendered

    assert panel.set_detail_level(ToolDetailLevel.FULL) is True
    assert panel.detail_level == ToolDetailLevel.FULL
    assert panel.expand_detail() is False


def test_tools_panel_detail_level_noops_without_content() -> None:
    panel = _build_panel()

    assert panel.expand_detail() is False
    assert panel.detail_level == ToolDetailLevel.COMPACT
