"""Tests for live runtime row patching in AgentList."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.widgets.agent_list import AgentList

from .agent_list_runtime_helpers import (
    AgentListHarness,
    agent,
    agent_row_index,
)


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_running_row() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        running_agent = agent(status="RUNNING", start=start)
        widget.update_list(
            [running_agent],
            current_idx=0,
            marked_agents={running_agent.identity},
            now=datetime(2026, 4, 25, 14, 0, 59),
        )
        await pilot.pause()

        row = agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "[✓]" in before
        assert before.rstrip().endswith("🏃‍♂️ 59s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after.rstrip().endswith("🏃‍♂️ 1m")


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_plan_approved_parent() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        parent = agent(
            agent_type=AgentType.WORKFLOW,
            status="PLAN APPROVED",
            start=start,
            raw_suffix="20260425140000",
        )
        parent.runtime_children.append(
            agent(
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

        row = agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "[✓]" in before
        assert before.rstrip().endswith("🏃‍♂️ 59s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after.rstrip().endswith("🏃‍♂️ 1m")


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_plan_approved_parent_times() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        parent = agent(
            agent_type=AgentType.WORKFLOW,
            status="PLAN APPROVED",
            start=datetime(2026, 4, 25, 14, 0, 0),
            plan_times=[datetime(2026, 4, 25, 14, 0, 30)],
            code_time=datetime(2026, 4, 25, 14, 0, 45),
            raw_suffix="20260425140000",
        )
        widget.update_list(
            [parent],
            current_idx=0,
            marked_agents={parent.identity},
            now=datetime(2026, 4, 25, 14, 0, 59),
        )
        await pilot.pause()

        row = agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "[✓]" in before
        assert before.rstrip().endswith("🏃‍♂️ 44s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after.rstrip().endswith("🏃‍♂️ 45s")


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_epic_approved_parent() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        parent = agent(
            agent_type=AgentType.WORKFLOW,
            status="EPIC APPROVED",
            start=start,
            raw_suffix="20260425140000",
        )
        parent.runtime_children.append(
            agent(
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

        row = agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert before.rstrip().endswith("🏃‍♂️ 59s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert after.rstrip().endswith("🏃‍♂️ 1m")


def test_patch_active_runtime_rows_skips_terminal_done_row() -> None:
    widget = AgentList()
    done_agent = agent(
        status="DONE",
        start=datetime(2026, 4, 25, 14, 0, 0),
        stop=datetime(2026, 4, 25, 14, 1, 0),
    )
    widget._agents = [done_agent]
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
    waiting_agent = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        run_start=None,
    )
    widget._agents = [waiting_agent]
    calls: list[int] = []

    def patch_agent_row(agent_idx: int, **_: object) -> bool:
        calls.append(agent_idx)
        return True

    widget.patch_agent_row = patch_agent_row  # type: ignore[method-assign]

    patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 2, 0))

    assert patched == 0
    assert calls == []


@pytest.mark.parametrize("status", ["PLANNING", "QUESTION", "WAITING INPUT"])
def test_patch_active_runtime_rows_skips_paused_parent_status(status: str) -> None:
    widget = AgentList()
    paused_parent = agent(
        agent_type=AgentType.WORKFLOW,
        status=status,
        start=datetime(2026, 4, 25, 14, 0, 0),
    )
    widget._agents = [paused_parent]
    calls: list[int] = []

    def patch_agent_row(agent_idx: int, **_: object) -> bool:
        calls.append(agent_idx)
        return True

    widget.patch_agent_row = patch_agent_row  # type: ignore[method-assign]

    patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 2, 0))

    assert patched == 0
    assert calls == []
