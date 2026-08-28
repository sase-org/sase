"""Tests for AgentList runtime suffix status markers and colors."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.agent.status_buckets import FEEDBACK_STATUS
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.gate_shell.status import gate_status_pair, gate_status_style

from .agent_list_runtime_helpers import agent


def test_format_agent_option_finished_suffix_has_timestamp_and_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    _, suffix, _ = format_agent_option(
        agent(status="DONE", start=start, stop=stop),
        0,
        is_selected=False,
        now=now,
    )
    assert suffix.plain == "20:17:03 · 6h17m"
    assert "✅" not in suffix.plain
    assert "❌" not in suffix.plain


def test_format_agent_option_unread_finished_suffix_has_completed_marker() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    left, suffix, _ = format_agent_option(
        agent(status="DONE", start=start, stop=stop),
        0,
        is_selected=False,
        is_unread=True,
        now=now,
    )
    assert "✦" not in left.plain
    assert suffix.plain == "20:17:03 · ✅ 6h17m"


def test_format_agent_option_planning_suffix_has_user_paused_marker() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    now = datetime(2026, 5, 6, 13, 23, 0)

    _, suffix, _ = format_agent_option(
        agent(
            agent_type=AgentType.WORKFLOW,
            status="PLAN",
            start=start,
            plan_times=[plan],
        ),
        0,
        is_selected=False,
        now=now,
    )

    assert suffix.plain == "13:14:53 · ✋ 5m53s"
    assert "🏃‍♂️" not in suffix.plain
    assert "✅" not in suffix.plain
    assert "❌" not in suffix.plain


def test_format_agent_option_question_without_time_has_user_paused_marker() -> None:
    _, suffix, _ = format_agent_option(
        agent(
            agent_type=AgentType.WORKFLOW,
            status="QUESTION",
            start=datetime(2026, 5, 6, 13, 9, 0),
        ),
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 13, 23, 0),
    )

    assert suffix.plain == "✋"


def test_format_agent_option_waiting_input_has_user_paused_marker() -> None:
    _, suffix, _ = format_agent_option(
        agent(
            agent_type=AgentType.WORKFLOW,
            status="WAITING INPUT",
            start=datetime(2026, 5, 6, 13, 9, 0),
        ),
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 13, 23, 0),
    )

    assert suffix.plain == "✋"


def test_format_agent_option_approved_plan_suffix_is_frozen() -> None:
    _, suffix, _ = format_agent_option(
        agent(
            agent_type=AgentType.WORKFLOW,
            status="PLAN APPROVED",
            start=datetime(2026, 5, 6, 13, 9, 0),
            run_start=datetime(2026, 5, 6, 13, 10, 7),
            plan_times=[datetime(2026, 5, 6, 13, 14, 53)],
            code_time=datetime(2026, 5, 6, 13, 15, 10),
        ),
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 13, 16, 15),
    )

    assert suffix.plain == "13:14:53 · 4m46s"
    assert "🏃‍♂️" not in suffix.plain
    assert "✋" not in suffix.plain


def test_format_agent_option_answered_active_suffix_has_running_marker() -> None:
    """An ANSWERED row with a run_start keeps ticking (no user-paused hand)."""
    _, suffix, _ = format_agent_option(
        agent(
            status="ANSWERED",
            start=datetime(2026, 5, 6, 14, 0, 0),
            run_start=datetime(2026, 5, 6, 14, 0, 0),
        ),
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 14, 5, 30),
    )

    assert suffix.plain == "🏃‍♂️ 5m30s"
    assert "✋" not in suffix.plain


def test_format_agent_option_answered_status_uses_gate_pair_style() -> None:
    """ANSWERED styling comes from the recorded question-gate status pair."""
    row_agent = agent(status="ANSWERED", start=datetime(2026, 5, 6, 14, 0, 0))
    row_agent.agent_family_role = "gate"
    row_agent.gate_id = "question-demo"
    row_agent.gate_state = "answered"
    row_agent.gate_start_status = "QUESTION"
    row_agent.gate_stop_status = "ANSWERED"
    row_agent.gate_accent = "#5FD7FF"

    left, _, _ = format_agent_option(
        row_agent,
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 14, 5, 0),
    )

    assert "ANSWERED ✓" in left.plain
    expected_style = gate_status_style(
        gate_status_pair("QUESTION", "ANSWERED"),
        gate_state="answered",
        accent="#5FD7FF",
    )
    answered_styles = [
        span.style
        for span in left.spans
        if left.plain[span.start : span.end] == "ANSWERED"
    ]
    assert answered_styles == [expected_style]


def test_format_agent_option_working_linked_coder_child_has_running_marker() -> None:
    row_agent = agent(
        status="WORKING TALE",
        start=datetime(2026, 5, 22, 18, 38, 12),
        run_start=datetime(2026, 5, 22, 18, 38, 39),
        role_suffix="-code",
        raw_suffix="20260522143839",
        cl_name="a1y.f1-code",
    )
    row_agent.parent_timestamp = "20260522143536"

    _, suffix, _ = format_agent_option(
        row_agent,
        0,
        is_selected=True,
        now=datetime(2026, 5, 22, 18, 41, 5),
    )

    assert suffix.plain == "🏃‍♂️ 2m26s"
    assert "✋" not in suffix.plain


@pytest.mark.parametrize(
    ("status", "expected_style"),
    [
        ("WORKING PLAN", "bold #00AF87"),
        ("WORKING TALE", "bold #00AFAF"),
    ],
)
def test_format_agent_option_plan_handoff_status_colors(
    status: str, expected_style: str
) -> None:
    left, _, _ = format_agent_option(
        agent(status=status, start=datetime(2026, 5, 6, 14, 0, 0)),
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 14, 5, 0),
    )

    assert status in left.plain
    styles = [
        span.style for span in left.spans if left.plain[span.start : span.end] == status
    ]
    assert styles == [expected_style]


@pytest.mark.parametrize(
    ("status", "gate_state", "start_status", "stop_status", "accent"),
    [
        ("TALE", "pending", "TALE", "TALE APPROVED", "#FF87AF"),
        ("EPIC", "pending", "EPIC", "EPIC APPROVED", "#D787FF"),
        ("QUESTION", "pending", "QUESTION", "ANSWERED", "#FFAF00"),
        ("PLAN APPROVED", "answered", "TALE", "PLAN APPROVED", "#00D7AF"),
        ("TALE APPROVED", "answered", "TALE", "TALE APPROVED", "#00D7D7"),
        ("PLAN COMMITTED", "answered", "TALE", "PLAN COMMITTED", "#5FD75F"),
        ("EPIC APPROVED", "answered", "EPIC", "EPIC APPROVED", "#5FD7AF"),
        (FEEDBACK_STATUS, "answered", "TALE", FEEDBACK_STATUS, "#FF5FD7"),
        ("PLAN REJECTED", "answered", "TALE", "PLAN REJECTED", "#D7AF5F"),
    ],
)
def test_format_agent_option_gate_status_uses_recorded_pair_style(
    status: str,
    gate_state: str,
    start_status: str,
    stop_status: str,
    accent: str,
) -> None:
    row_agent = agent(status=status, start=datetime(2026, 5, 6, 14, 0, 0))
    row_agent.agent_family_role = "gate"
    row_agent.gate_id = "plan-demo"
    row_agent.gate_state = gate_state
    row_agent.gate_start_status = start_status
    row_agent.gate_stop_status = stop_status
    row_agent.gate_accent = accent

    left, _, _ = format_agent_option(
        row_agent,
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 14, 5, 0),
    )

    assert status in left.plain
    expected_style = gate_status_style(
        gate_status_pair(start_status, stop_status),
        gate_state=gate_state,
        accent=accent,
    )
    styles = [
        span.style for span in left.spans if left.plain[span.start : span.end] == status
    ]
    assert styles == [expected_style]


def test_format_agent_option_unread_terminal_suffix_uses_completed_marker() -> None:
    _, suffix, _ = format_agent_option(
        agent(status="DONE", start=None),
        0,
        is_selected=False,
        is_unread=True,
    )

    assert suffix.plain == "✅"
    assert "✋" not in suffix.plain


def test_format_agent_option_unread_failed_suffix_uses_failed_marker() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    _, suffix, _ = format_agent_option(
        agent(status="FAILED", start=start, stop=stop),
        0,
        is_selected=False,
        is_unread=True,
        now=now,
    )
    assert suffix.plain == "20:17:03 · ❌ 6h17m"


def test_format_agent_option_unread_failed_prefix_uses_failed_marker() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    _, suffix, _ = format_agent_option(
        agent(status="FAILED CRASH", start=start, stop=stop),
        0,
        is_selected=False,
        is_unread=True,
        now=now,
    )
    assert suffix.plain == "20:17:03 · ❌ 6h17m"
    assert "✅" not in suffix.plain
