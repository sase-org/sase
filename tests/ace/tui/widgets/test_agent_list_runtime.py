"""Tests for the right-aligned runtime + finish-timestamp suffix."""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.app import App

from sase.ace.tui.models.agent import (
    Agent,
    AgentType,
    compute_row_runtime,
)
from sase.ace.tui.models.agent_time import (
    _format_finish_timestamp,
    runtime_suffix_ticks,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.agent_list import AgentList


def _agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    run_start: datetime | None = None,
    stop: datetime | None = None,
    raw_suffix: str = "20260425143000",
    cl_name: str = "demo",
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/p.gp",
        status=status,
        start_time=start,
        run_start_time=run_start,
        stop_time=stop,
        raw_suffix=raw_suffix,
    )


class _Harness(App):
    """Mount a single AgentList for row-patching tests."""

    def compose(self):
        yield AgentList(id="agent-list")


def _agent_row_index(widget: AgentList, agent_idx: int) -> int:
    return widget._row_index_for_agent(agent_idx)  # type: ignore[return-value]


# --- _format_finish_timestamp ------------------------------------------------


def test__format_finish_timestamp_same_day() -> None:
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("", "20:17:03")


def test__format_finish_timestamp_prior_day_same_year() -> None:
    stop = datetime(2026, 4, 24, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("Apr 24 ", "20:17")


def test__format_finish_timestamp_prior_year() -> None:
    stop = datetime(2025, 12, 31, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("Dec 31 '25", "")


# --- compute_row_runtime ----------------------------------------------------


def test_compute_row_runtime_active_returns_elapsed_only() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 38, 45)
    ts, elapsed = compute_row_runtime(_agent(start=start), now=now)
    assert ts is None
    assert elapsed == "38m45s"


def test_compute_row_runtime_uses_run_start_when_present() -> None:
    """A long WAIT period should not inflate runtime."""
    start = datetime(2026, 4, 25, 13, 0, 0)
    run_start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    ts, elapsed = compute_row_runtime(_agent(start=start, run_start=run_start), now=now)
    assert ts is None
    assert elapsed == "5m"


def test_compute_row_runtime_finished_today() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    ts, elapsed = compute_row_runtime(
        _agent(status="DONE", start=start, stop=stop), now=now
    )
    assert ts == ("", "20:17:03")
    # >= 1h: hours and minutes
    assert elapsed == "6h17m"


def test_compute_row_runtime_finished_yesterday() -> None:
    start = datetime(2026, 4, 24, 19, 38, 18)
    stop = datetime(2026, 4, 24, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    ts, elapsed = compute_row_runtime(
        _agent(status="DONE", start=start, stop=stop), now=now
    )
    assert ts == ("Apr 24 ", "20:17")
    assert elapsed == "38m45s"


def test_compute_row_runtime_no_start_returns_nones() -> None:
    ts, elapsed = compute_row_runtime(_agent(start=None), now=datetime.now())
    assert ts is None
    assert elapsed is None


def test_compute_row_runtime_pure_waiting_returns_nones() -> None:
    """A WAITING agent that hasn't started yet renders no runtime suffix."""
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    ts, elapsed = compute_row_runtime(
        _agent(status="WAITING", start=start, run_start=None), now=now
    )
    assert ts is None
    assert elapsed is None


# --- runtime_suffix_ticks ----------------------------------------------------


def test_runtime_suffix_ticks_active_parent_status() -> None:
    agent = _agent(status="PLAN APPROVED")
    assert runtime_suffix_ticks(agent) is True


def test_runtime_suffix_ticks_parent_with_active_followup() -> None:
    parent = _agent(status="PLANNING")
    child = _agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    parent.followup_agents.append(child)

    assert runtime_suffix_ticks(parent) is True


def test_runtime_suffix_ticks_stopped_parent_with_active_followup_is_stable() -> None:
    parent = _agent(
        status="PLAN APPROVED",
        stop=datetime(2026, 4, 25, 14, 31, 0),
    )
    child = _agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    parent.followup_agents.append(child)

    assert runtime_suffix_ticks(parent) is False


# --- row rendering / batch alignment ----------------------------------------


def test_format_agent_option_active_suffix_contains_only_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 38, 45)
    _, suffix, _ = format_agent_option(
        _agent(start=start), 0, is_selected=False, now=now
    )
    assert suffix.plain == "38m45s"


def test_format_agent_option_finished_suffix_has_timestamp_and_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    _, suffix, _ = format_agent_option(
        _agent(status="DONE", start=start, stop=stop),
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
        _agent(status="DONE", start=start, stop=stop),
        0,
        is_selected=False,
        now=now,
    )
    assert suffix.plain == "Apr 24 20:17 · 38m45s"


def test_format_agent_option_no_start_has_empty_suffix() -> None:
    _, suffix, _ = format_agent_option(
        _agent(start=None), 0, is_selected=False, now=datetime.now()
    )
    assert suffix.plain == ""


def test_format_agent_option_pure_waiting_has_empty_suffix() -> None:
    _, suffix, _ = format_agent_option(
        _agent(status="WAITING", run_start=None),
        0,
        is_selected=False,
        now=datetime.now(),
    )
    assert suffix.plain == ""


def test_update_list_right_aligns_suffixes_across_batch() -> None:
    """All suffixes line up to the same right edge after layout."""
    widget = AgentList()
    short_active = _agent(
        cl_name="a",
        raw_suffix="20260425140000",
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 0),
    )
    long_done = _agent(
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
    rows: list[str] = []
    for opt in list(widget._options):  # type: ignore[attr-defined]
        if opt.id and (opt.id.startswith("0:") or opt.id.startswith("1:")):
            rows.append(opt.prompt.plain)  # type: ignore[union-attr]
    assert len(rows) == 2
    # The DONE row's suffix ends in the formatted finish-timestamp + elapsed.
    assert rows[1].rstrip().endswith("20:17:03 · 6h17m")
    # Both rows render at the same total cell width (right-aligned column).
    assert len(rows[0]) == len(rows[1])
    assert widget._requested_width == widget._target_width + 8


# --- active runtime row patching ---------------------------------------------


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_running_row() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        agent = _agent(status="RUNNING", start=start)
        widget.update_list(
            [agent],
            current_idx=0,
            marked_agents={agent.identity},
            now=datetime(2026, 4, 25, 14, 0, 59),
        )
        await pilot.pause()

        row = _agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "[✓]" in before
        assert before.rstrip().endswith("59s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after.rstrip().endswith("1m")


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_plan_approved_parent() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        parent = _agent(
            agent_type=AgentType.WORKFLOW,
            status="PLAN APPROVED",
            start=start,
            raw_suffix="20260425140000",
        )
        parent.followup_agents.append(
            _agent(
                status="RUNNING",
                start=start,
                raw_suffix="20260425140100",
                cl_name="demo.code",
            )
        )
        widget.update_list(
            [parent],
            current_idx=0,
            marked_agents={parent.identity},
            now=datetime(2026, 4, 25, 14, 0, 59),
        )
        await pilot.pause()

        row = _agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "[✓]" in before
        assert before.rstrip().endswith("59s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after.rstrip().endswith("1m")


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_epic_approved_parent() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        parent = _agent(
            agent_type=AgentType.WORKFLOW,
            status="EPIC APPROVED",
            start=start,
            raw_suffix="20260425140000",
        )
        parent.followup_agents.append(
            _agent(
                status="RUNNING",
                start=start,
                raw_suffix="20260425140100",
                cl_name="demo.epic",
            )
        )
        widget.update_list(
            [parent],
            current_idx=0,
            now=datetime(2026, 4, 25, 14, 0, 59),
        )
        await pilot.pause()

        row = _agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert before.rstrip().endswith("59s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert after.rstrip().endswith("1m")


def test_patch_active_runtime_rows_skips_terminal_done_row() -> None:
    widget = AgentList()
    agent = _agent(
        status="DONE",
        start=datetime(2026, 4, 25, 14, 0, 0),
        stop=datetime(2026, 4, 25, 14, 1, 0),
    )
    widget._agents = [agent]
    calls: list[int] = []

    def patch_agent_row(agent_idx: int, **_: object) -> bool:
        calls.append(agent_idx)
        return True

    widget.patch_agent_row = patch_agent_row  # type: ignore[method-assign]

    patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 2, 0))

    assert patched == 0
    assert calls == []


def test_patch_active_runtime_rows_skips_waiting_without_run_start() -> None:
    widget = AgentList()
    agent = _agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        run_start=None,
    )
    widget._agents = [agent]
    calls: list[int] = []

    def patch_agent_row(agent_idx: int, **_: object) -> bool:
        calls.append(agent_idx)
        return True

    widget.patch_agent_row = patch_agent_row  # type: ignore[method-assign]

    patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 2, 0))

    assert patched == 0
    assert calls == []
