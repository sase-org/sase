from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools._constants import MAX_VISIBLE_SLOW_TOOL_CALLS
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_slow_tools import (
    append_slow_tool_calls_section,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-07-03T14:00:00+00:00",
        "runtime": "codex",
        "event": "ToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "call_1",
        "duration_ms": 20_000,
        "tool_input_summary": {"command": "just test"},
        "tool_response_summary": {"exit_code": 0},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def test_empty_slow_tools_section_appends_nothing() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        candidates=(),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    assert text.plain == ""


def test_slow_tools_section_renders_summary_and_completed_row() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        candidates=(_entry(duration_ms=92_000),),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert "SLOW TOOL CALLS · ≥20s · 1 call" in plain
    assert "14:00:00" in plain
    assert "✔ Bash" in plain
    assert "just test" in plain
    assert "1m 32s" in plain


def test_slow_tools_section_renders_running_badge() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        candidates=(
            _entry(
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:00:00+00:00",
            ),
        ),
        agent=SimpleNamespace(status="RUNNING", stop_time=None),
        now=datetime(2026, 7, 3, 14, 0, 30, tzinfo=UTC),
    )

    plain = text.plain
    assert "1 call · 1 running" in plain
    assert "⏳ Bash" in plain
    assert "30s ● running" in plain


def test_slow_tools_section_renders_did_not_complete() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        candidates=(
            _entry(
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:00:00+00:00",
            ),
        ),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 10, tzinfo=UTC),
        agent_end_reference=datetime(2026, 7, 3, 14, 0, 45, tzinfo=UTC),
    )

    plain = text.plain
    assert "◼ Bash" in plain
    assert "45s did not complete" in plain


def test_slow_tools_section_overflow_points_to_tools_timeline() -> None:
    text = Text()
    entries = tuple(
        _entry(tool_use_id=f"call_{index}", duration_ms=20_000 + index)
        for index in range(MAX_VISIBLE_SLOW_TOOL_CALLS + 2)
    )

    append_slow_tool_calls_section(
        text,
        candidates=entries,
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert plain.count("✔ Bash") == MAX_VISIBLE_SLOW_TOOL_CALLS
    assert "+ 2 more · press ] for the full tools timeline" in plain


def test_slow_tools_section_truncates_long_targets() -> None:
    text = Text()
    long_command = "echo " + ("x" * 120)

    append_slow_tool_calls_section(
        text,
        candidates=(_entry(tool_input_summary={"command": long_command}),),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert long_command not in plain
    assert "…" in plain
