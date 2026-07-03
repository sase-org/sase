from __future__ import annotations

from datetime import UTC, datetime

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools.slow import (
    format_long_duration,
    select_slow_tool_calls,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


def test_format_long_duration_promotes_minutes() -> None:
    assert format_long_duration(92_000) == "1m 32s"
    assert format_long_duration(120_000) == "2m"
    assert format_long_duration(3_600_000) == "1h"


def test_pending_active_call_crosses_threshold_live() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:00:00+00:00",
            ),
        ),
        now=_dt("2026-07-03T14:00:21+00:00"),
        agent_is_active=True,
        agent_end_reference=None,
    )

    assert len(selected) == 1
    assert selected[0].is_running is True
    assert selected[0].effective_duration_ms == 21_000


def test_completed_duration_threshold_is_inclusive() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(tool_use_id="under", duration_ms=19_999),
            _entry(tool_use_id="exact", duration_ms=20_000),
            _entry(tool_use_id="over", duration_ms=20_001),
        ),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
        agent_is_active=False,
        agent_end_reference=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    assert [item.entry.tool_use_id for item in selected] == ["over", "exact"]


def test_completed_missing_duration_uses_completed_at() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(
                duration_ms=None,
                recorded_at="2026-07-03T14:00:00+00:00",
                completed_at="2026-07-03T14:00:25+00:00",
            ),
        ),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
        agent_is_active=False,
        agent_end_reference=None,
    )

    assert len(selected) == 1
    assert selected[0].effective_duration_ms == 25_000
    assert selected[0].is_running is False


def test_pending_terminated_call_uses_stable_end_reference() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:00:00+00:00",
            ),
        ),
        now=_dt("2026-07-03T14:10:00+00:00"),
        agent_is_active=False,
        agent_end_reference=_dt("2026-07-03T14:00:45+00:00"),
    )

    assert len(selected) == 1
    assert selected[0].did_not_complete is True
    assert selected[0].is_running is False
    assert selected[0].effective_duration_ms == 45_000


def test_subagent_markers_are_excluded() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(
                event="SubagentStart",
                status="subagent",
                tool_name=None,
                duration_ms=90_000,
            ),
        ),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
        agent_is_active=False,
        agent_end_reference=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
    )

    assert selected == ()


def test_clock_skew_clamps_negative_duration() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:01:00+00:00",
            ),
        ),
        now=_dt("2026-07-03T14:00:00+00:00"),
        agent_is_active=True,
        agent_end_reference=None,
    )

    assert selected == ()


def test_ordering_puts_running_first_then_slowest_completed() -> None:
    selected = select_slow_tool_calls(
        (
            _entry(tool_use_id="completed-slow", duration_ms=70_000),
            _entry(
                tool_use_id="running-shorter",
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:00:30+00:00",
            ),
            _entry(tool_use_id="completed-fast", duration_ms=25_000),
            _entry(
                tool_use_id="running-longer",
                status="pending",
                duration_ms=None,
                recorded_at="2026-07-03T14:00:00+00:00",
            ),
        ),
        now=_dt("2026-07-03T14:01:00+00:00"),
        agent_is_active=True,
        agent_end_reference=None,
    )

    assert [item.entry.tool_use_id for item in selected] == [
        "running-longer",
        "running-shorter",
        "completed-slow",
        "completed-fast",
    ]
