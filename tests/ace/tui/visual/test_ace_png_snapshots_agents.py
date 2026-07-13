"""ACE TUI PNG visual snapshot coverage for Agents-tab list states.

ChangeSpecs-tab and footer snapshots live in ``test_ace_png_snapshots``.
Agents-tab modal and detail snapshots live in sibling
``test_ace_png_snapshots_agents_*`` modules.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    agents_with_stopped_status,
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _pin_agents_visual_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Pin Agents-tab runtime formatting for date-sensitive snapshots."""
    from sase.ace.tui.actions.agents import (
        _display_panel_patches,
        _loading_compute_finalize,
        _loading_finalize,
    )
    from sase.ace.tui.models import agent as agent_module
    from sase.ace.tui.models import agent_time

    for module in (
        agent_module,
        agent_time,
        _display_panel_patches,
        _loading_compute_finalize,
        _loading_finalize,
    ):
        monkeypatch.setattr(module, "local_now", lambda: now)


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
        )


async def test_agent_reverted_indicator_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = agents()
    rows[0].reverted = True
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "↺")
        ace_png_visual.assert_page_png(
            page,
            "agents_reverted_indicator_120x40",
            title="ACE agents reverted indicator",
        )


async def test_agent_stopped_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents_with_stopped_status())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Ø STOPPED")
        ace_png_visual.assert_page_png(
            page,
            "agents_stopped_status_120x40",
            title="ACE agents stopped status",
        )


def _plan_handoff_status_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan-approved",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN APPROVED",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            raw_suffix="20260509-100000-plan-approved",
            agent_name="plan.approved",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-tale-approved",
            project_file="/workspace/sase/visual_project.sase",
            status="TALE APPROVED",
            start_time=datetime(2026, 5, 9, 10, 1, 0),
            raw_suffix="20260509-100100-tale-approved",
            agent_name="tale.approved",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-working-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="WORKING PLAN",
            start_time=datetime(2026, 5, 9, 10, 2, 0),
            raw_suffix="20260509-100200-working-plan",
            agent_name="working.plan",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-working-tale",
            project_file="/workspace/sase/visual_project.sase",
            status="WORKING TALE",
            start_time=datetime(2026, 5, 9, 10, 3, 0),
            raw_suffix="20260509-100300-working-tale",
            agent_name="working.tale",
        ),
    ]


def _waiting_family_child_agents() -> list[Agent]:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 5, 21, 0, 0),
        raw_suffix="20260705-210000-parent",
        agent_name="visual-parent",
        llm_provider="codex",
        model="gpt-5",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent--reviewer",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 5, 21, 1, 0),
        run_start_time=None,
        wait_start_time=datetime(2026, 7, 5, 21, 1, 0),
        raw_suffix="20260705-210100-reviewer",
        parent_timestamp=parent.raw_suffix,
        agent_name="visual-parent--reviewer",
        agent_family="visual-parent",
        agent_family_role="reviewer",
        role_suffix="--reviewer",
        waiting_for=["visual-parent"],
        llm_provider="codex",
        model="gpt-5",
    )
    return [parent, child]


def _runner_slot_wait_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-drain-barrier",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 12, 1, 0),
            raw_suffix="20260712120100",
            artifacts_dir="/workspace/sase/artifacts/ace-run/20260712120100",
            agent_name="drain-barrier",
            pid=4102,
            wait_runners=0,
            wait_runners_explicit=True,
            slot_requested_at="2026-07-12T12:01:00Z",
            runner_slots_in_use=0,
            runner_slot_queue_position=2,
            runner_slot_queue_size=2,
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-global-cap",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 12, 0, 0),
            raw_suffix="20260712120000",
            artifacts_dir="/workspace/sase/artifacts/ace-run/20260712120000",
            agent_name="global-cap",
            pid=4101,
            wait_runners=9,
            wait_runners_explicit=False,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=0,
            runner_slot_queue_position=1,
            runner_slot_queue_size=2,
            llm_provider="claude",
            model="sonnet",
        ),
    ]


def _custom_role_label_agents() -> list[Agent]:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-custom-family",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 6, 10, 0, 0),
        raw_suffix="20260706100000",
        role_suffix="--plan",
        agent_name="visual-custom",
        agent_family="visual-custom",
        agent_family_role="root",
        plan_chain_root=True,
        llm_provider="codex",
        model="gpt-5",
    )
    improve = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-custom--improve_plan",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 6, 10, 2, 0),
        raw_suffix="20260706100200",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--improve_plan",
        agent_name="visual-custom--improve_plan",
        agent_family="visual-custom",
        agent_family_role="improve_plan",
        custom_role_label="IMPROVING PLAN",
        custom_role_done_label="PLAN IMPROVED",
        llm_provider="codex",
        model="gpt-5",
    )
    tester = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-custom--tester",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 6, 10, 4, 0),
        stop_time=datetime(2026, 7, 6, 10, 8, 0),
        raw_suffix="20260706100400",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--tester",
        agent_name="visual-custom--tester",
        agent_family="visual-custom",
        agent_family_role="tester",
        custom_role_label="TESTING",
        custom_role_done_label="TESTED",
        llm_provider="codex",
        model="gpt-5",
    )
    rows = [parent, improve, tester]
    _apply_status_overrides(rows)
    return rows


def _output_variable_family_agents() -> list[Agent]:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 0, 0),
        stop_time=datetime(2026, 7, 8, 9, 9, 0),
        raw_suffix="20260708090000",
        role_suffix="--plan",
        agent_name="visual-output-vars",
        agent_family="visual-output-vars",
        agent_family_role="root",
        plan_chain_root=True,
        llm_provider="codex",
        model="gpt-5",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars--code",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 1, 0),
        stop_time=datetime(2026, 7, 8, 9, 7, 0),
        raw_suffix="20260708090100",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--code",
        agent_name="visual-output-vars--code",
        agent_family="visual-output-vars",
        agent_family_role="code",
        output_variables={
            "build_report": "/workspace/sase/out/build-report.md",
            "summary": "tests passed\ncoverage updated",
        },
        llm_provider="codex",
        model="gpt-5",
    )
    question = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-output-vars--q",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 8, 9, 3, 0),
        stop_time=datetime(2026, 7, 8, 9, 5, 0),
        raw_suffix="20260708090300",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--q",
        agent_name="visual-output-vars--q",
        agent_family="visual-output-vars",
        agent_family_role="q",
        output_variables={
            "answer_path": "/workspace/sase/out/user-answer.md",
            "summary": "approval captured",
        },
        llm_provider="codex",
        model="gpt-5",
    )
    rows = [parent, coder, question]
    _apply_status_overrides(rows)
    return rows


async def test_agent_plan_handoff_status_colors_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_plan_handoff_status_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        for status in (
            "PLAN APPROVED",
            "TALE APPROVED",
            "WORKING PLAN",
            "WORKING TALE",
        ):
            assert_page_svg_contains(page, status)
        ace_png_visual.assert_page_png(
            page,
            "agents_plan_handoff_status_colors_120x40",
            title="ACE agents plan handoff status colors",
        )


async def test_waiting_family_child_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_waiting_family_child_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-parent")
        assert_page_svg_contains(page, "RUNNING")
        assert_page_svg_contains(page, "visual-parent--reviewer")
        assert_page_svg_contains(page, "WAITING")
        ace_png_visual.assert_page_png(
            page,
            "agents_waiting_family_child_120x40",
            title="ACE agents waiting family child",
        )


async def test_runner_slot_wait_rows_and_queue_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_runner_slot_wait_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        selected = page.app._agents[page.app.current_idx]
        assert selected.runner_slot_queue_position == 2
        assert selected.runner_slot_queue_size == 2
        assert_page_svg_contains(page, "drain-barrier")
        assert_page_svg_contains(page, "global-cap")
        assert_page_svg_contains(page, "drain barrier")
        assert_page_svg_contains(page, "eligible")
        ace_png_visual.assert_page_png(
            page,
            "agents_runner_slot_waits_120x40",
            title="ACE agents runner slot waits",
        )


async def test_custom_role_labels_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 6, 10, 8, 0))
    patch_startup_loaders(monkeypatch, agents=_custom_role_label_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "IMPROVING PLAN")
        assert_page_svg_contains(page, "TESTED")
        ace_png_visual.assert_page_png(
            page,
            "agents_custom_role_labels_120x40",
            title="ACE agents custom role labels",
        )


async def test_agent_output_variables_multi_agent_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 8, 9, 9, 0))
    patch_startup_loaders(monkeypatch, agents=_output_variable_family_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "OUTPUT VARIABLES")
        assert_page_svg_contains(page, "2 agents")
        assert_page_svg_contains(page, "build_report")
        assert_page_svg_contains(page, "answer_path")
        ace_png_visual.assert_page_png(
            page,
            "agents_output_variables_multi_agent_120x40",
            title="ACE agents output variables multi agent",
        )


async def test_agents_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        initial_idx = page.app.current_idx
        for _ in range(8):
            await page.press("j")
            if page.app.current_idx != initial_idx:
                break
        else:
            raise AssertionError("j navigation did not move off the initial agent row")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_selected_row_120x40",
            title="ACE agents selected row",
        )
