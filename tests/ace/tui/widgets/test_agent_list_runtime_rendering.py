"""Tests for AgentList runtime suffix rendering and alignment."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

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
            agent(
                agent_type=AgentType.WORKFLOW,
                status="PLAN APPROVED",
                start=datetime(2026, 4, 25, 14, 4, 0),
            ),
            "🏃‍♂️ 1m",
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


def test_format_agent_option_no_start_has_empty_suffix() -> None:
    _, suffix, _ = format_agent_option(
        agent(start=None), 0, is_selected=False, now=datetime.now()
    )
    assert suffix.plain == ""


def test_format_agent_option_renders_tag_label_only_when_passed() -> None:
    row_agent = agent(cl_name="demo", raw_suffix="20260425140000")

    left_without, _, _ = format_agent_option(row_agent, 0, is_selected=False)
    left_with, _, _ = format_agent_option(
        row_agent,
        0,
        is_selected=False,
        tag_label="fix",
    )

    assert " #fix" not in left_without.plain
    assert " #fix" in left_with.plain


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
