"""ACE TUI PNG visual snapshots for Agents-tab auto-approve metadata."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _auto_approve_agents() -> list[Agent]:
    """Three running agents, one per auto-approve kind, for the row-icon snapshot.

    ``approve`` stays ``True`` for every kind (it drives the ⚡ glyph); the
    ``auto_approve_plan_action`` selects the ⚡ / ⚡T / ⚡E suffix.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            approve=True,
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-tale",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 1, 0),
            raw_suffix="20260509-100100-tale",
            agent_name="teller",
            approve=True,
            auto_approve_plan_action="tale",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-epic",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 2, 0),
            raw_suffix="20260509-100200-epic",
            agent_name="epicer",
            approve=True,
            auto_approve_plan_action="epic",
        ),
    ]


def _auto_approve_workflow_child_agents() -> list[Agent]:
    """Expanded workflow family for auto-approve child-row alignment coverage."""
    root_timestamp = "20260509-100000-workflow"
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 5, 9, 10, 0, 0)
    return [
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="visual-auto-workflow",
            project_file=project_file,
            status="EPIC APPROVED",
            start_time=started,
            raw_suffix=root_timestamp,
            workflow="sase",
            approve=True,
            auto_approve_plan_action="epic",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="main",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 5),
            raw_suffix=root_timestamp,
            workflow="sase",
            parent_workflow="sase",
            parent_timestamp=root_timestamp,
            step_name="main",
            step_type="agent",
            step_index=0,
            total_steps=4,
            agent_name="visual.sase--plan",
            approve=True,
            auto_approve_plan_action="epic",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="setup",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 10),
            raw_suffix=root_timestamp,
            workflow="sase",
            parent_workflow="sase",
            parent_timestamp=root_timestamp,
            step_name="setup",
            step_type="bash",
            step_index=1,
            total_steps=4,
            agent_name="visual.setup",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="diff",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 15),
            raw_suffix=root_timestamp,
            workflow="sase",
            parent_workflow="sase",
            parent_timestamp=root_timestamp,
            step_name="diff",
            step_type="python",
            step_index=2,
            total_steps=4,
            agent_name="visual.diff",
        ),
    ]


async def test_agents_auto_approve_icons_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_svg_contains(page, "⚡T ")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "⚡ ")
        assert_page_svg_contains(page, "⚡T ")
        assert_page_svg_contains(page, "⚡E ")

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_icons_120x40",
            title="ACE agents auto-approve icons",
        )


async def test_agents_auto_approve_workflow_child_alignment_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_workflow_child_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        page.app._fold_manager.expand("20260509-100000-workflow")
        page.app._refilter_agents()
        await page.expect_state("agent_count", 4)
        await wait_for_svg_contains(page, "⚡E ")
        await wait_for_visual_idle(page)

        svg_plain = page.export_svg(title="ACE auto child alignment").replace(
            "&#160;",
            " ",
        )
        assert svg_plain.count("⚡E ") == 2
        for token in ("sase", "main", "setup", "diff", "🐚 ", "🐍 "):
            assert token in svg_plain
        connector_positions = re.findall(
            r'x="([^"]+)" y="([^"]+)"[^>]*>  └─ </text>',
            svg_plain,
        )
        assert len(connector_positions) == 3
        assert len({x for x, _ in connector_positions}) == 1
        connector_y = {y for _, y in connector_positions}
        child_bolt_positions = [
            (x, y)
            for x, y in re.findall(
                r'x="([^"]+)" y="([^"]+)"[^>]*>⚡E </text>',
                svg_plain,
            )
            if y in connector_y
        ]
        assert len(child_bolt_positions) == 1
        assert float(child_bolt_positions[0][0]) > float(connector_positions[0][0])

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_workflow_child_alignment_120x40",
            title="ACE agents auto-approve workflow child alignment",
        )


async def test_agents_auto_approve_metadata_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        for idx, (token, snapshot_name, title) in enumerate(
            (
                ("⚡ PLAN", "agents_auto_approve_metadata_plan_120x40", "PLAN"),
                ("⚡ TALE", "agents_auto_approve_metadata_tale_120x40", "TALE"),
                ("⚡ EPIC", "agents_auto_approve_metadata_epic_120x40", "EPIC"),
            )
        ):
            if idx:
                await page.press("j")
            await wait_for_state(
                page,
                lambda idx=idx: page.app.current_idx == idx,
                description=f"selected auto-approve agent index {idx}",
            )
            await wait_for_svg_contains(page, token)
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "Auto:")
            assert_page_svg_contains(page, token)

            ace_png_visual.assert_page_png(
                page,
                snapshot_name,
                title=f"ACE agents auto-approve metadata {title}",
            )


def _auto_approve_xprompts_agent(artifacts_dir: Path) -> Agent:
    """One approved agent whose artifacts dir carries ``xprompts.json``.

    Exercises the combined metadata layout where the ``Auto:`` and ``Model:``
    fields render in order immediately before the disk-enriched ``Xprompts:``
    section.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "xprompts.json").write_text(
        json.dumps(
            [
                {"kind": "workflow", "name": "auto_before_xprompts"},
                {"kind": "part", "name": "plan_part"},
            ]
        ),
        encoding="utf-8",
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-plan",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 9, 10, 0, 0),
        raw_suffix="20260509-100000-plan",
        agent_name="planner",
        approve=True,
        llm_provider="claude",
        model="opus",
        artifacts_dir=str(artifacts_dir),
    )


async def test_agents_auto_approve_xprompts_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = _auto_approve_xprompts_agent(tmp_path / "xprompt-artifacts")
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Xprompts:")
        await wait_for_visual_idle(page)

        svg = page.export_svg(title="ACE auto/xprompts metadata")
        svg_plain = svg.replace("&#160;", " ")
        assert "Auto:" in svg_plain
        assert "Model:" in svg_plain
        assert "Xprompts:" in svg_plain
        assert (
            svg_plain.index("Auto:")
            < svg_plain.index("Model:")
            < svg_plain.index("Xprompts:")
        )

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_xprompts_metadata_120x40",
            title="ACE agents auto-approve xprompts metadata",
        )
