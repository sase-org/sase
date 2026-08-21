"""Tests for live runtime row patching in AgentList."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.agent_completion import (
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
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
async def test_normal_refresh_removes_missing_wait_marker_when_target_appears() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        waiting = agent(status="WAITING", run_start=None)
        waiting.agent_name = "waiter"
        waiting.waiting_for = ["target-outside-panel"]
        app._agents_with_children = [waiting]

        widget.update_list([waiting], current_idx=0)
        await pilot.pause()

        row = agent_row_index(widget, 0)
        missing_prompt = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "(WAITING ?1)" in missing_prompt
        assert widget._row_render_ctx[0]["wait_dependency_counts"] == (
            WaitDependencyStatusCounts(agents=WaitAgentStatusCounts(unknown=1))
        )

        target = agent(
            status="RUNNING",
            raw_suffix="20260425143100",
            cl_name="target",
        )
        target.agent_name = "target-outside-panel"
        app._agents_with_children = [waiting, target]

        widget.update_list([waiting], current_idx=0)
        await pilot.pause()

        refreshed_prompt = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "(WAITING ?1)" not in refreshed_prompt
        assert "(WAITING ▶1)" in refreshed_prompt
        assert widget._row_render_ctx[0]["wait_dependency_counts"] == (
            WaitDependencyStatusCounts(agents=WaitAgentStatusCounts(running=1))
        )


@pytest.mark.asyncio
async def test_patch_row_replaces_stale_bead_wait_counts() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        waiting = agent(status="WAITING", run_start=None)
        waiting.agent_name = "waiter"
        waiting.waiting_for_beads = ["run-bead"]
        app._agents_with_children = [waiting]

        widget.update_list([waiting], current_idx=0)
        await pilot.pause()

        row = agent_row_index(widget, 0)
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "(WAITING)" in before
        assert "◐1" not in before

        widget._target_width = max(widget._target_width, 80)
        patched = widget.patch_agent_row(
            0,
            wait_dependency_counts=WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(in_progress=1)
            ),
        )
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched is True
        assert "(WAITING ◐1)" in after
        assert widget._row_render_ctx[0]["wait_dependency_counts"] == (
            WaitDependencyStatusCounts(beads=WaitBeadStatusCounts(in_progress=1))
        )

        widget._target_width = 8
        grew = widget.patch_agent_row(
            0,
            wait_dependency_counts=WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(in_progress=12)
            ),
        )
        assert grew is False
        assert widget._row_render_ctx[0]["wait_dependency_counts"] == (
            WaitDependencyStatusCounts(beads=WaitBeadStatusCounts(in_progress=1))
        )


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
async def test_patch_active_runtime_rows_skips_frozen_approved_plan() -> None:
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
        assert before.rstrip().endswith("14:00:30 · 30s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 0
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after == before


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_advances_approved_linked_coder_child() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        child = agent(
            status="TALE APPROVED",
            start=datetime(2026, 5, 22, 18, 38, 12),
            run_start=datetime(2026, 5, 22, 18, 38, 39),
            role_suffix="-code",
            raw_suffix="20260522143839",
            cl_name="a1y.f1-code",
        )
        child.parent_timestamp = "20260522143536"
        widget.update_list(
            [child],
            current_idx=0,
            marked_agents={child.identity},
            now=datetime(2026, 5, 22, 18, 41, 5),
        )
        await pilot.pause()

        row = agent_row_index(widget, 0)
        before_count = widget.option_count
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert "[✓]" in before
        assert before.rstrip().endswith("🏃‍♂️ 2m26s")

        patched = widget.patch_active_runtime_rows(datetime(2026, 5, 22, 18, 41, 6))
        await pilot.pause()

        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert widget.option_count == before_count
        assert "[✓]" in after
        assert after.rstrip().endswith("🏃‍♂️ 2m27s")


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


def test_patch_active_runtime_rows_includes_waiting_time_floor_without_run_start() -> (
    None
):
    widget = AgentList()
    waiting_agent = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        run_start=None,
    )
    waiting_agent.wait_until = "2026-04-25T14:05:00"
    widget._agents = [waiting_agent]
    calls: list[int] = []

    def patch_agent_row(agent_idx: int, **_: object) -> bool:
        calls.append(agent_idx)
        return True

    widget.patch_agent_row = patch_agent_row  # type: ignore[method-assign]

    patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 2, 0))

    assert patched == 1
    assert calls == [0]


@pytest.mark.parametrize("status", ["PLAN", "QUESTION", "WAITING INPUT"])
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
