from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.tools._constants import MAX_VISIBLE_SLOW_TOOL_CALLS
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_slow_tools import (
    append_slow_tool_calls_section,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_logical_section_is_compact,
    assert_rendered_section_is_compact,
)
from tests.ace.tui.widgets._agent_slow_tools_helpers import (
    make_entry as _entry,
    make_source as _source,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def test_empty_slow_tools_section_appends_nothing() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    assert text.plain == ""


def test_slow_tools_section_renders_summary_and_completed_row() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(_source(_entry(duration_ms=92_000)),),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert "SLOW TOOL CALLS · ≥20s · 1 call" in plain
    assert "14:00:00" in plain
    assert "✔ Bash" in plain
    assert "just test" in plain
    assert "1m 32s" in plain
    heading = "▸ SLOW TOOL CALLS · ≥20s · 1 call"
    assert_logical_section_is_compact(text, heading, "  14:00:00")
    assert_rendered_section_is_compact(text, heading, "  14:00:00")


def test_slow_tools_section_uses_custom_threshold_label_and_filter() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(
                _entry(
                    tool_use_id="under",
                    duration_ms=29_999,
                    tool_input_summary={"command": "under threshold"},
                ),
                _entry(
                    tool_use_id="exact",
                    duration_ms=30_000,
                    tool_input_summary={"command": "exact threshold"},
                ),
            ),
        ),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        threshold_ms=30_000,
    )

    plain = text.plain
    assert "SLOW TOOL CALLS · ≥30s · 1 call" in plain
    assert "exact threshold" in plain
    assert "under threshold" not in plain


def test_slow_tools_section_renders_running_badge() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(
                _entry(
                    status="pending",
                    duration_ms=None,
                    recorded_at="2026-07-03T14:00:00+00:00",
                ),
                active=True,
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
        sources=(
            _source(
                _entry(
                    status="pending",
                    duration_ms=None,
                    recorded_at="2026-07-03T14:00:00+00:00",
                ),
                end_reference=datetime(2026, 7, 3, 14, 0, 45, tzinfo=UTC),
            ),
        ),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 10, tzinfo=UTC),
    )

    plain = text.plain
    assert "◼ Bash" in plain
    assert "45s did not complete" in plain


def test_slow_tools_section_overflow_points_to_tools_timeline() -> None:
    text = Text()
    entries = tuple(
        _entry(
            tool_use_id=f"call_{index}",
            duration_ms=20_000 + index,
            recorded_at=f"2026-07-03T14:00:{index:02d}+00:00",
            tool_input_summary={"command": f"call {index}"},
        )
        for index in range(MAX_VISIBLE_SLOW_TOOL_CALLS + 2)
    )

    append_slow_tool_calls_section(
        text,
        sources=(_source(*entries),),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert plain.count("✔ Bash") == MAX_VISIBLE_SLOW_TOOL_CALLS
    assert "call 0" not in plain
    assert "call 1" not in plain
    assert "call 2" in plain
    assert f"call {MAX_VISIBLE_SLOW_TOOL_CALLS + 1}" in plain
    assert "+ 2 more · press ] for the full tools timeline" in plain


def test_slow_tools_section_keeps_running_call_when_capped() -> None:
    text = Text()
    running = _entry(
        tool_use_id="running",
        status="pending",
        duration_ms=None,
        recorded_at="2026-07-03T14:00:00+00:00",
        tool_input_summary={"command": "running long"},
    )
    completed = tuple(
        _entry(
            tool_use_id=f"completed_{index}",
            duration_ms=20_000,
            recorded_at=f"2026-07-03T14:00:{index:02d}+00:00",
            tool_input_summary={"command": f"completed {index}"},
        )
        for index in range(1, MAX_VISIBLE_SLOW_TOOL_CALLS + 1)
    )

    append_slow_tool_calls_section(
        text,
        sources=(_source(running, *completed, active=True),),
        agent=SimpleNamespace(status="RUNNING", stop_time=None),
        now=datetime(2026, 7, 3, 14, 10, tzinfo=UTC),
    )

    plain = text.plain
    assert "running long" in plain
    assert "completed 1" not in plain
    assert "completed 2" in plain
    assert f"completed {MAX_VISIBLE_SLOW_TOOL_CALLS}" in plain
    assert "+ 1 more · press ] for the full tools timeline" in plain


def test_slow_tools_section_truncates_long_targets() -> None:
    text = Text()
    long_command = "echo " + ("x" * 120)

    append_slow_tool_calls_section(
        text,
        sources=(_source(_entry(tool_input_summary={"command": long_command})),),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert long_command not in plain
    assert "…" in plain


def test_slow_tools_section_renders_source_chips_and_agent_count() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(_entry(tool_use_id="plan", duration_ms=24_000), label="plan"),
            _source(
                _entry(
                    tool_use_id="code",
                    duration_ms=58_000,
                    tool_input_summary={"command": "gh pr checks --watch"},
                ),
                label="code",
                palette_index=1,
            ),
        ),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    plain = text.plain
    assert "SLOW TOOL CALLS · ≥20s · 2 calls · 2 agents" in plain
    assert "✔ code" in plain
    assert "✔ plan" in plain
    assert "gh pr checks --watch" in plain


def test_slow_tools_section_orders_by_start_time_across_sources() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(
                _entry(
                    tool_use_id="running",
                    status="pending",
                    duration_ms=None,
                    recorded_at="2026-07-03T14:00:10+00:00",
                    tool_input_summary={"command": "running middle"},
                ),
                label="code",
                active=True,
            ),
            _source(
                _entry(
                    tool_use_id="completed-early",
                    duration_ms=90_000,
                    recorded_at="2026-07-03T14:00:00+00:00",
                    tool_input_summary={"command": "completed early"},
                ),
                _entry(
                    tool_use_id="completed-late",
                    duration_ms=90_000,
                    recorded_at="2026-07-03T14:00:20+00:00",
                    tool_input_summary={"command": "completed late"},
                ),
                label="plan",
                palette_index=1,
            ),
        ),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    plain = text.plain
    assert plain.index("completed early") < plain.index("running middle")
    assert plain.index("running middle") < plain.index("completed late")


def test_slow_tools_section_ties_use_source_order() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(
                _entry(
                    tool_use_id="first",
                    duration_ms=20_000,
                    recorded_at="2026-07-03T14:00:00+00:00",
                    line_number=99,
                    tool_input_summary={"command": "first source"},
                ),
                label="first",
            ),
            _source(
                _entry(
                    tool_use_id="second",
                    duration_ms=90_000,
                    recorded_at="2026-07-03T14:00:00+00:00",
                    line_number=1,
                    tool_input_summary={"command": "second source"},
                ),
                label="second",
                palette_index=1,
            ),
        ),
        agent=SimpleNamespace(status="DONE", stop_time=None),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    plain = text.plain
    assert plain.index("first source") < plain.index("second source")


def test_slow_tools_section_uses_per_source_pending_state() -> None:
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(
                _entry(
                    tool_use_id="dead",
                    status="pending",
                    duration_ms=None,
                    recorded_at="2026-07-03T14:00:00+00:00",
                    tool_input_summary={"command": "dead child"},
                ),
                label="plan",
                end_reference=datetime(2026, 7, 3, 14, 0, 45, tzinfo=UTC),
            ),
            _source(
                _entry(
                    tool_use_id="live",
                    status="pending",
                    duration_ms=None,
                    recorded_at="2026-07-03T14:00:30+00:00",
                    tool_input_summary={"command": "live child"},
                ),
                label="code",
                active=True,
                palette_index=1,
            ),
        ),
        agent=SimpleNamespace(status="RUNNING", stop_time=None),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    plain = text.plain
    assert "45s did not complete" in plain
    assert "30s ● running" in plain
