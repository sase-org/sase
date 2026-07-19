"""Tests for AgentList runtime suffix rendering and alignment."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

from sase.agent.status_buckets import FEEDBACK_STATUS
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.agent_list import AgentList

from .agent_list_runtime_helpers import agent, workflow_child


def test_format_agent_option_active_suffix_contains_only_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 38, 45)
    _, suffix, _ = format_agent_option(
        agent(start=start), 0, is_selected=False, now=now
    )
    assert suffix.plain == "🏃‍♂️ 38m45s"


@pytest.mark.parametrize(
    ("runtime_agent", "expected"),
    [
        (
            agent(
                status="WAITING",
                start=datetime(2026, 4, 25, 13, 0, 0),
                run_start=datetime(2026, 4, 25, 14, 0, 0),
            ),
            "🏃‍♂️ 5m",
        ),
        (
            agent(
                status="RETRYING",
                start=datetime(2026, 4, 25, 14, 4, 48),
            ),
            "🏃‍♂️ 12s",
        ),
        (
            workflow_child(
                step_type="agent",
                status="RUNNING",
                start=datetime(2026, 4, 25, 14, 2, 55),
            ),
            "🏃‍♂️ 2m05s",
        ),
    ],
)
def test_format_agent_option_live_suffix_has_runtime_marker(
    runtime_agent: Agent, expected: str
) -> None:
    now = datetime(2026, 4, 25, 14, 5, 0)
    _, suffix, _ = format_agent_option(runtime_agent, 0, is_selected=False, now=now)
    assert suffix.plain == expected


def test_format_agent_option_aggregate_parent_uses_interval_union() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLAN APPROVED",
        start=datetime(2026, 5, 6, 13, 9, 0),
    )
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 5, 6, 13, 9, 0),
        run_start=datetime(2026, 5, 6, 13, 10, 7),
        plan_times=[datetime(2026, 5, 6, 13, 13, 3)],
        cl_name="plan",
    )
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 5, 6, 13, 13, 10),
        run_start=datetime(2026, 5, 6, 13, 13, 10),
        raw_suffix="20260506131310",
        cl_name="demo.code",
    )
    parent.runtime_children.extend([planner, coder])

    _, suffix, _ = format_agent_option(
        parent,
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 13, 16, 15),
    )

    assert suffix.plain == "🏃‍♂️ 6m01s"


def test_format_agent_option_aggregate_parent_does_not_double_count_overlap() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="DONE",
        start=datetime(2026, 7, 17, 10, 0, 0),
    )
    first = agent(
        status="DONE",
        start=datetime(2026, 7, 17, 10, 0, 0),
        run_start=datetime(2026, 7, 17, 10, 0, 0),
        stop=datetime(2026, 7, 17, 10, 10, 0),
        raw_suffix="first",
    )
    second = agent(
        status="DONE",
        start=datetime(2026, 7, 17, 10, 5, 0),
        run_start=datetime(2026, 7, 17, 10, 5, 0),
        stop=datetime(2026, 7, 17, 10, 15, 0),
        raw_suffix="second",
    )
    parent.runtime_children.extend([first, second])

    _, suffix, _ = format_agent_option(
        parent,
        0,
        is_selected=False,
        now=datetime(2026, 7, 17, 10, 20, 0),
    )

    assert suffix.plain == "10:15:00 · 15m"


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


def test_format_agent_option_answered_status_uses_explicit_style() -> None:
    """The ANSWERED status renders with its explicit bright-azure style."""
    left, _, _ = format_agent_option(
        agent(status="ANSWERED", start=datetime(2026, 5, 6, 14, 0, 0)),
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 14, 5, 0),
    )

    assert "ANSWERED" in left.plain
    answered_styles = [
        span.style
        for span in left.spans
        if left.plain[span.start : span.end] == "ANSWERED"
    ]
    assert answered_styles == ["bold #5FD7FF"]


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
        ("PLAN APPROVED", "bold #00D7AF"),
        ("TALE APPROVED", "bold #00D7D7"),
        ("WORKING PLAN", "bold #00AF87"),
        ("WORKING TALE", "bold #00AFAF"),
        (FEEDBACK_STATUS, "bold #FF5FD7"),
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


def test_format_agent_option_finished_yesterday_suffix_human_readable() -> None:
    start = datetime(2026, 4, 24, 19, 38, 18)
    stop = datetime(2026, 4, 24, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    _, suffix, _ = format_agent_option(
        agent(status="DONE", start=start, stop=stop),
        0,
        is_selected=False,
        now=now,
    )
    assert suffix.plain == "Apr 24 20:17 · 38m45s"


def test_format_agent_option_appears_as_agent_prompt_step_done_suffix() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    run_start = datetime(2026, 4, 25, 14, 1, 0)
    stop = datetime(2026, 4, 25, 14, 2, 30)
    now = datetime(2026, 4, 25, 14, 3, 0)
    _, suffix, _ = format_agent_option(
        workflow_child(
            step_type="agent",
            status="DONE",
            start=start,
            run_start=run_start,
            stop=stop,
            cl_name="main",
            parent_appears_as_agent=True,
        ),
        0,
        is_selected=False,
        now=now,
    )
    assert suffix.plain == "14:02:30 · 1m30s"


def test_format_agent_option_done_plan_step_uses_plan_time_suffix() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    now = datetime(2026, 5, 6, 13, 15, 27)
    _, suffix, _ = format_agent_option(
        workflow_child(
            step_type="agent",
            status="DONE",
            start=start,
            run_start=run_start,
            plan_times=[plan],
            cl_name="plan",
            parent_appears_as_agent=True,
        ),
        0,
        is_selected=False,
        now=now,
    )
    assert suffix.plain == "13:14:53 · 4m46s"


def test_format_agent_option_plan_done_row_uses_plan_time_suffix() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    stop = datetime(2026, 5, 6, 13, 22, 40)
    now = datetime(2026, 5, 6, 13, 23, 0)

    _, suffix, _ = format_agent_option(
        agent(
            status="PLAN DONE",
            start=start,
            stop=stop,
            plan_times=[plan],
            code_time=datetime(2026, 5, 6, 13, 15, 10),
            role_suffix=".plan",
        ),
        0,
        is_selected=False,
        now=now,
    )

    assert suffix.plain == "13:14:53 · 5m53s"


def test_format_agent_option_done_plan_step_prefers_plan_time_over_stop_time() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    stop = datetime(2026, 5, 6, 13, 22, 40)
    now = datetime(2026, 5, 6, 13, 23, 0)

    _, suffix, _ = format_agent_option(
        workflow_child(
            step_type="agent",
            status="DONE",
            start=start,
            run_start=run_start,
            stop=stop,
            plan_times=[plan],
            code_time=datetime(2026, 5, 6, 13, 15, 10),
            cl_name="plan",
            role_suffix=".plan",
            parent_appears_as_agent=True,
        ),
        0,
        is_selected=False,
        now=now,
    )

    assert suffix.plain == "13:14:53 · 4m46s"


def test_format_agent_option_no_start_has_empty_suffix() -> None:
    _, suffix, _ = format_agent_option(
        agent(start=None), 0, is_selected=False, now=datetime.now()
    )
    assert suffix.plain == ""


def test_format_agent_option_renders_tribe_label_only_when_passed() -> None:
    row_agent = agent(cl_name="demo", raw_suffix="20260425140000")

    left_without, _, _ = format_agent_option(row_agent, 0, is_selected=False)
    left_with, _, _ = format_agent_option(
        row_agent,
        0,
        is_selected=False,
        tribe_label="fix",
    )

    assert " @fix" not in left_without.plain
    assert " @fix" in left_with.plain


def test_format_agent_option_renders_unread_marker_in_suffix_not_before_mark() -> None:
    row_agent = agent(
        cl_name="demo",
        raw_suffix="20260425140000",
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 45, 0),
    )

    left, suffix, _ = format_agent_option(
        row_agent,
        0,
        is_selected=False,
        is_marked=True,
        is_unread=True,
    )

    assert "[✓]" in left.plain
    assert "✦" not in left.plain
    assert suffix.plain.endswith("✅ 15m")


def test_format_agent_option_omits_unread_marker_by_default() -> None:
    row_agent = agent(cl_name="demo", raw_suffix="20260425140000")

    left, suffix, _ = format_agent_option(row_agent, 0, is_selected=False)

    assert "✦" not in left.plain
    assert "✅" not in suffix.plain
    assert "❌" not in suffix.plain


def test_format_agent_option_unread_without_runtime_uses_marker_only_suffix() -> None:
    left, suffix, _ = format_agent_option(
        agent(status="DONE", start=None),
        0,
        is_selected=False,
        is_unread=True,
    )

    assert "✦" not in left.plain
    assert suffix.plain == "✅"


def test_format_agent_option_keeps_tribe_badge_and_agent_name_prefixes_distinct() -> (
    None
):
    row_agent = agent(cl_name="demo", raw_suffix="20260425140000")
    row_agent.agent_name = "coder"

    left, _, _ = format_agent_option(
        row_agent,
        0,
        is_selected=False,
        tribe_label="fix",
    )

    assert " @fix" in left.plain
    assert " coder" in left.plain
    assert " [coder]" not in left.plain
    assert " [fix]" not in left.plain
    assert " @coder" not in left.plain


def test_format_agent_option_pure_waiting_has_empty_suffix() -> None:
    _, suffix, _ = format_agent_option(
        agent(status="WAITING", run_start=None),
        0,
        is_selected=False,
        now=datetime.now(),
    )
    assert suffix.plain == ""


def test_format_agent_option_non_agent_workflow_child_has_empty_suffix() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 14, 1, 30)
    _, suffix, _ = format_agent_option(
        workflow_child(step_type="python", status="DONE", start=start, stop=stop),
        0,
        is_selected=False,
        now=datetime(2026, 4, 25, 14, 2, 0),
    )
    assert suffix.plain == ""


def test_update_list_right_aligns_suffixes_across_batch() -> None:
    """All suffixes line up to the same right edge after layout."""
    widget = AgentList()
    short_active = agent(
        cl_name="a",
        raw_suffix="20260425140000",
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 0),
    )
    long_done = agent(
        cl_name="much-longer-agent-name",
        raw_suffix="20260425141500",
        status="DONE",
        start=datetime(2026, 4, 25, 14, 0, 0),
        stop=datetime(2026, 4, 25, 20, 17, 3),
    )
    widget.update_list(
        [short_active, long_done],
        current_idx=0,
        now=datetime(2026, 4, 25, 21, 0, 0),
    )
    # Pull the rendered rows for the two agent options (skip banners).
    rows: list[Text] = []
    for opt in list(widget._options):  # type: ignore[attr-defined]
        if opt.id and (opt.id.startswith("0:") or opt.id.startswith("1:")):
            rows.append(opt.prompt)  # type: ignore[arg-type]
    assert len(rows) == 2
    assert rows[0].plain.rstrip().endswith("🏃‍♂️ 7h")
    # The DONE row's suffix ends in the formatted finish-timestamp + elapsed.
    assert rows[1].plain.rstrip().endswith("20:17:03 · 6h17m")
    # Both rows render at the same total cell width (right-aligned column).
    assert rows[0].cell_len == rows[1].cell_len
    assert widget._requested_width == widget._target_width + 8
