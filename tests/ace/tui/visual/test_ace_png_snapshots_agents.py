"""ACE TUI PNG visual snapshot coverage for Agents-tab list states.

ChangeSpecs-tab and footer snapshots live in ``test_ace_png_snapshots``.
Agents-tab modal and detail snapshots live in sibling
``test_ace_png_snapshots_agents_*`` modules.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
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
        agent_family="visual-parent",
        agent_family_role="root",
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
    parent.followup_agents = [child]
    return [parent, child]


def _parallel_family_agents() -> list[Agent]:
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parallel-family",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 16, 10, 0, 0),
        raw_suffix="20260716100000",
        agent_name="visual-parallel-family",
        agent_family="visual-parallel-family",
        agent_family_role="root",
        agent_family_parallel=True,
        llm_provider="codex",
        model="gpt-5",
    )
    members = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-parallel-phase-{index}",
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=datetime(2026, 7, 16, 10, index, 0),
            run_start_time=(
                datetime(2026, 7, 16, 10, index, 30) if status == "RUNNING" else None
            ),
            stop_time=(datetime(2026, 7, 16, 10, 6, 0) if status == "DONE" else None),
            raw_suffix=f"20260716100{index}00",
            parent_timestamp=root.raw_suffix,
            agent_name=f"visual-parallel-phase-{index}",
            agent_family="visual-parallel-family",
            agent_family_role="phase",
            agent_family_parallel=True,
            llm_provider="codex",
            model="gpt-5",
        )
        for index, status in enumerate(("RUNNING", "RUNNING", "DONE"), start=1)
    ]
    rows = [root, *members]
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _clan_tree_agents(*, clan_summary: str | None = None) -> list[Agent]:
    generation = "20260717100000"
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-research-family",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 10, 2, 0),
        run_start_time=datetime(2026, 7, 17, 10, 2, 0),
        raw_suffix="20260717100200-family",
        agent_name="research.family",
        agent_clan="research",
        agent_clan_generation=generation,
        clan_summary=clan_summary,
        agent_family="research.family",
        agent_family_role="root",
        tribe="epic",
        llm_provider="codex",
        model="gpt-5",
    )
    family_member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-research-family-code",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 10, 4, 0),
        run_start_time=datetime(2026, 7, 17, 10, 4, 0),
        raw_suffix="20260717100400-family-code",
        parent_timestamp=family.raw_suffix,
        role_suffix="--code",
        agent_name="research.family--code",
        agent_family="research.family",
        agent_family_role="code",
        agent_clan="research",
        agent_clan_generation=generation,
        llm_provider="codex",
        model="gpt-5",
    )
    workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="visual-research-audit",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        stop_time=datetime(2026, 7, 17, 10, 8, 0),
        raw_suffix="20260717100000-audit",
        workflow="audit",
        agent_name="research.audit",
        agent_clan="research",
        agent_clan_generation=generation,
        tribe="review",
    )
    workflow_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="audit-prompt",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 1, 0),
        run_start_time=datetime(2026, 7, 17, 10, 1, 0),
        stop_time=datetime(2026, 7, 17, 10, 7, 0),
        raw_suffix="20260717100100-audit-prompt",
        parent_workflow="audit",
        parent_timestamp=workflow.raw_suffix,
        agent_family="research.audit",
        step_name="audit",
        step_type="agent",
        step_index=0,
        total_steps=2,
        llm_provider="claude",
        model="sonnet",
    )
    hidden_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="audit-setup",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 0, 30),
        run_start_time=datetime(2026, 7, 17, 10, 0, 30),
        stop_time=datetime(2026, 7, 17, 10, 0, 45),
        raw_suffix="20260717100030-audit-setup",
        parent_workflow="audit",
        parent_timestamp=workflow.raw_suffix,
        agent_family="research.audit",
        step_name="setup",
        step_type="bash",
        step_index=1,
        total_steps=2,
        is_hidden_step=True,
    )
    waiting = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-research-waiting",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 17, 10, 3, 0),
        raw_suffix="20260717100300-waiting",
        agent_name="research.waiting",
        agent_clan="research",
        agent_clan_generation=generation,
        tribe="epic",
        waiting_for=["research.family"],
        llm_provider="gemini",
        model="gemini-pro",
    )
    return sort_and_reorder(
        [family, family_member, workflow, waiting],
        [workflow_step, hidden_step],
    )


def _epic_clan_agents() -> list[Agent]:
    generation = "20260717120000"

    def member(
        name: str,
        status: str,
        minute: int,
        *,
        stop_minute: int | None = None,
        model: str,
        provider: str,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-{name}",
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=datetime(2026, 7, 17, 12, minute, 0),
            run_start_time=datetime(2026, 7, 17, 12, minute, 0),
            stop_time=(
                datetime(2026, 7, 17, 12, stop_minute, 0)
                if stop_minute is not None
                else None
            ),
            raw_suffix=f"2026071712{minute:02d}00-{name}",
            agent_name=f"sase-6n.{name}",
            agent_clan="sase-6n",
            agent_clan_generation=generation,
            agent_family_role="land" if name == "land" else "phase",
            tribe="epic",
            llm_provider=provider,
            model=model,
        )

    return sort_and_reorder(
        [
            member(
                "phase-runtime",
                "DONE",
                0,
                stop_minute=7,
                model="gpt-5",
                provider="codex",
            ),
            member(
                "phase-tui",
                "DONE",
                2,
                stop_minute=9,
                model="sonnet",
                provider="claude",
            ),
            member(
                "land",
                "RUNNING",
                9,
                model="gemini-pro",
                provider="gemini",
            ),
        ],
        [],
    )


def _decorate_clan_panel_sections(rows: list[Agent]) -> list[Agent]:
    """Give panel-only fixtures representative in-memory aggregate sections."""
    container = next(row for row in rows if row.is_clan_container)
    members = [container]
    for direct_member in container.runtime_children:
        members.append(direct_member)
        members.extend(
            row
            for row in rows
            if row.agent_clan is not None
            and row.tree_parent_key == direct_member.raw_suffix
        )
    assert len(members) >= 3
    for index, member in enumerate(members, start=1):
        member.output_variables = {
            "summary": f"member {index} complete\nfull visual detail",
        }
        member.workspace_num = index
    members[1].error_message = "Snapshot review found a rendering mismatch"
    members[1].error_traceback = "VisualDiffError: expected clan section glyph"
    members[1].step_output = {
        "meta_review": "check fold indicators\ninspect every level",
    }
    members[-1].activity = "integrating clan summary"
    return rows


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


def _renamed_plan_family_agents() -> list[Agent]:
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-family-root",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 11, 0, 0),
        stop_time=datetime(2026, 7, 18, 11, 4, 0),
        raw_suffix="20260718110000",
        role_suffix="--plan",
        agent_name="cx--plan",
        agent_family="cx",
        agent_family_role="root",
        plan_chain_root=True,
        llm_provider="codex",
        model="gpt-5",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-family-code",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 11, 5, 0),
        stop_time=datetime(2026, 7, 18, 11, 10, 0),
        raw_suffix="20260718110500",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name="cx--code",
        agent_family="cx",
        agent_family_role="code",
        llm_provider="codex",
        model="gpt-5",
    )
    rows = [root, coder]
    _apply_status_overrides(rows)
    return rows


def _family_and_lone_planner_agents() -> list[Agent]:
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-real-family",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 12, 0, 0),
        stop_time=datetime(2026, 7, 18, 12, 4, 0),
        raw_suffix="20260718120000",
        role_suffix="--plan",
        agent_name="visual-real-family--plan",
        agent_family="visual-real-family",
        agent_family_role="root",
        plan_chain_root=True,
        appears_as_agent=True,
    )
    member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-real-family-code",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 12, 5, 0),
        stop_time=datetime(2026, 7, 18, 12, 8, 0),
        raw_suffix="20260718120500",
        parent_timestamp=family.raw_suffix,
        role_suffix="--code",
        agent_name="visual-real-family--code",
        agent_family="visual-real-family",
        agent_family_role="code",
    )
    lone_planner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-lone-planner",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 12, 10, 0),
        stop_time=datetime(2026, 7, 18, 12, 15, 0),
        raw_suffix="20260718121000",
        role_suffix="--plan",
        agent_name="visual-lone-planner--plan",
        agent_family="visual-lone-planner",
        agent_family_role="root",
        plan_chain_root=True,
        appears_as_agent=True,
    )
    rows = [family, member, lone_planner]
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


async def test_renamed_plan_family_root_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 11, 10, 0))
    patch_startup_loaders(monkeypatch, agents=_renamed_plan_family_agents())

    async with AcePage(query='"visual-family"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert page.app._agents[0].agent_name == "cx--plan"
        assert page.app._agents[0].presented_agent_name == "cx"
        assert_page_svg_contains(page, "cx--plan")
        assert_page_svg_contains(page, "cx--code")
        ace_png_visual.assert_page_png(
            page,
            "agents_renamed_plan_family_root_120x40",
            title="ACE renamed plan family root",
        )


async def test_parallel_family_root_counts_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 16, 10, 10, 0))
    patch_startup_loaders(monkeypatch, agents=_parallel_family_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-parallel-family")
        assert_page_svg_styled_text_contains(page, "[R2 D1]")
        # (unread, stopped, running, waiting, failed, done, total, starting)
        assert page.app._agent_info_metrics() == (0, 0, 2, 0, 0, 1, 3, 0)
        ace_png_visual.assert_page_png(
            page,
            "agents_parallel_family_counts_120x40",
            title="ACE parallel family aggregate counts",
        )


async def test_family_and_lone_planner_color_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 12, 15, 0))
    rows = _family_and_lone_planner_agents()
    family = next(row for row in rows if row.cl_name == "visual-real-family")
    lone_planner = next(row for row in rows if row.cl_name == "visual-lone-planner")
    assert family.is_family_container_row is True
    assert lone_planner.is_family_container_row is False
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-real-family")
        assert_page_svg_contains(page, "visual-lone-planner")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_and_lone_planner_color_120x40",
            title="ACE family and lone planner color contrast",
        )


async def test_clan_tree_fold_levels_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 17, 10, 15, 0))
    patch_startup_loaders(monkeypatch, agents=_clan_tree_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert page.app._agents[0].is_clan_container is True
        assert page.app._agents[0].clan_tribes == ("epic", "review")
        assert_page_svg_contains(page, "research")
        assert_page_svg_styled_text_contains(page, "[R1 W1 D1]")
        assert_page_svg_contains(page, "@epic")
        assert_page_svg_contains(page, "@review")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_collapsed_120x40",
            title="ACE clan tree collapsed",
        )

        await page.press("l")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "research.family")
        assert_page_svg_contains(page, "research.audit")
        assert all(
            agent.agent_name != "research.family--code" for agent in page.app._agents
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_expanded_120x40",
            title="ACE clan tree expanded",
        )

        await page.press("j", "j", "j")
        assert page.app._agents[page.app.current_idx].agent_name == "research.audit"
        await page.press("l")
        await page.expect_state("agent_count", 5)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "audit-prompt")
        assert all(not agent.is_hidden_step for agent in page.app._agents)
        assert all(
            agent.agent_name != "research.family--code" for agent in page.app._agents
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_member_expanded_120x40",
            title="ACE clan member expanded",
        )

        await page.press("l")
        await page.expect_state("agent_count", 6)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "setup")
        assert all(
            agent.agent_name != "research.family--code" for agent in page.app._agents
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_fully_expanded_120x40",
            title="ACE clan member fully expanded",
        )

        await page.press("o", "o")
        await wait_for_visual_idle(page)
        assert page.app._grouping_mode is GroupingMode.BY_STATUS
        assert page.app._panel_group.panel_keys == [None]
        status_group_keys = [
            entry.group.group_key
            for entry in build_agent_tree(
                page.app._agents,
                mode=GroupingMode.BY_STATUS,
            )
            if entry.group is not None
        ]
        assert status_group_keys == [("Running",)]
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_fully_expanded_by_status_120x40",
            title="ACE clan member fully expanded by status",
        )


async def test_clan_unread_count_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 17, 10, 15, 0))
    patch_startup_loaders(monkeypatch, agents=_clan_tree_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)

        unread_member = next(
            agent
            for agent in page.app._agents_with_children
            if not agent.is_clan_container
            and agent.tree_depth == 1
            and agent.status == "DONE"
        )
        page.app._unread_completed_agent_ids.add(unread_member.identity)
        page.app._manual_unread_agent_ids.add(unread_member.identity)
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        assert_page_svg_styled_text_contains(page, "[R1 W1 U1]")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_unread_collapsed_120x40",
            title="ACE unread clan collapsed",
        )

        await page.press("l")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)
        assert_page_svg_styled_text_contains(page, "[R1 W1 U1]")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_unread_expanded_120x40",
            title="ACE unread clan expanded",
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
        assert_page_svg_contains(page, "· 4")
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
