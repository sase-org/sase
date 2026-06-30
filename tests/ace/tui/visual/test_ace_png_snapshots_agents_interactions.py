"""ACE TUI PNG visual snapshot coverage for Agents-tab interaction states."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    hood_neighbor_agents,
    patch_startup_loaders,
    visual_agents,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _done_agents() -> list[Agent]:
    """Three completed agents in the ``Done`` bucket.

    Used by the unread-highlight snapshot — all three rows are then
    marked unread post-startup so the Agents-tab info-panel header
    renders a non-zero ``N unread`` count that exercises the yellow
    background style.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


async def test_agents_unread_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _done_agents()
    patch_startup_loaders(monkeypatch, agents=done)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        identities = {agent.identity for agent in done}
        page.app._unread_completed_agent_ids = set(identities)
        page.app._manual_unread_agent_ids = set(identities)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app._update_agents_info_panel()
        from sase.ace.tui.widgets import AgentInfoPanel

        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        assert panel._unread_count == 3, f"expected 3 unread, got {panel._unread_count}"
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_unread_highlight_120x40",
            title="ACE agents unread highlight",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_neighbor_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)
        neighbor_index = page.app._agent_neighbor_index()
        assert neighbor_index.neighbor_count(page.app.current_idx) == 2
        assert_page_svg_contains(page, "neighbors: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_neighbor_badge_120x40",
            title="ACE agents neighbor badge",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_neighbor_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentNeighborModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2]
        assert_page_svg_contains(page, "Neighbors of visual.code.plan")
        assert_page_svg_contains(page, "visual.code.implementation")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_60x30",
            title="ACE agent neighbor modal narrow",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_neighbor_modal_dismissed_descendant_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 13, 0, 0),
        raw_suffix="20260523-130000-parent",
        agent_name="visual.root",
        tag="api",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-child",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 8, 0),
        stop_time=datetime(2026, 5, 23, 13, 12, 30),
        raw_suffix="20260523-130800-child",
        agent_name="visual.root.visible",
        tag="api",
    )
    dismissed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-dismissed",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 16, 0),
        stop_time=datetime(2026, 5, 23, 13, 17, 5),
        raw_suffix="20260523-131600-dismissed",
        agent_name="visual.root.dismissed",
        tag="api",
    )
    patch_startup_loaders(monkeypatch, agents=[parent, child])

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        page.app._dismissed_agent_objects = [dismissed]
        page.app._dismissed_agents = {dismissed.identity}
        page.app._dismiss_revive_epoch += 1
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Descendants")
        assert_page_svg_contains(page, "visual.root.dismissed")
        assert_page_svg_contains(page, "dismissed")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_descendants_dismissed_60x30",
            title="ACE agent neighbor modal dismissed descendant",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _workspace_tmux_choices() -> list:
    from sase.ace.tui.modals.agent_workspace_tmux_modal import (
        AgentWorkspaceTmuxChoice,
    )

    return [
        AgentWorkspaceTmuxChoice(
            kind="current",
            label="workspaces_lane",
            window_name="",
            project_name="sase",
            workspace_dir="~/.sase/sase_12",
        ),
        AgentWorkspaceTmuxChoice(
            kind="linked",
            label="sase-core",
            window_name="sase-core_12",
            workspace_dir="/w/sase-core_12",
            reason="Need Rust backend context",
            agent_label="code",
        ),
        AgentWorkspaceTmuxChoice(
            kind="linked",
            label="bob",
            window_name="bob_12",
            workspace_dir="/w/bob_12",
            reason="Compare Obsidian workflow",
        ),
    ]


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


async def test_agents_auto_approve_icons_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "⚡ ")
        assert_page_svg_contains(page, "⚡T ")
        assert_page_svg_contains(page, "⚡E ")

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_icons_120x40",
            title="ACE agents auto-approve icons",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_auto_approve_metadata_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        for idx, (token, snapshot_name, title) in enumerate(
            (
                ("⚡ PLAN", "agents_auto_approve_metadata_plan_120x40", "PLAN"),
                ("⚡ TALE", "agents_auto_approve_metadata_tale_120x40", "TALE"),
                ("⚡ EPIC", "agents_auto_approve_metadata_epic_120x40", "EPIC"),
            )
        ):
            if idx:
                await page.press("j")
                await wait_for_visual_idle(page)
            assert page.app.current_idx == idx
            assert_page_svg_contains(page, "Auto:")
            assert_page_svg_contains(page, token)

            ace_png_visual.assert_page_png(
                page,
                snapshot_name,
                title=f"ACE agents auto-approve metadata {title}",
                max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
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
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_auto_approve_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        from sase.ace.tui.modals.auto_approve_modal import AutoApproveModal

        page.app.push_screen(AutoApproveModal("epic", agent_name="visual.code"))
        await page.expect_modal("AutoApproveModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Auto-Approve")
        assert_page_svg_contains(page, "Plan")
        assert_page_svg_contains(page, "Tale")
        assert_page_svg_contains(page, "Epic")
        assert_page_svg_contains(page, "Disable")
        assert_page_svg_contains(page, "visual.code")

        ace_png_visual.assert_page_png(
            page,
            "auto_approve_modal_60x30",
            title="ACE auto-approve modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_workspace_tmux_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(100, 28)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        from sase.ace.tui.modals.agent_workspace_tmux_modal import (
            AgentWorkspaceTmuxModal,
        )

        page.app.push_screen(AgentWorkspaceTmuxModal(_workspace_tmux_choices()))
        await page.expect_modal("AgentWorkspaceTmuxModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Tmux Workspace")
        assert_page_svg_contains(page, "CURRENT")
        assert_page_svg_contains(page, "LINKED")
        assert_page_svg_contains(page, "sase-core")
        assert_page_svg_contains(page, "Rust backend")

        ace_png_visual.assert_page_png(
            page,
            "agent_workspace_tmux_modal_100x28",
            title="ACE agent workspace tmux modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_wait_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(100, 32)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        from sase.ace.tui.modals.wait_modal import WaitAgentCandidate, WaitModal

        page.app.push_screen(
            WaitModal(
                current_wait_duration=300.0,
                candidates=[
                    WaitAgentCandidate(
                        wait_name="visual.plan.review.contract.snapshot",
                        label="visual.plan.review.contract.snapshot",
                        status="RUNNING",
                        model="codex / gpt-5",
                        start_time="13:00",
                        duration="4m",
                        role="root",
                    ),
                    WaitAgentCandidate(
                        wait_name="visual.code.implementation.with.narrow.row",
                        label="visual.code.implementation.with.narrow.row",
                        status="DONE",
                        model="claude / sonnet",
                        start_time="13:08",
                        duration="4m30s",
                        tag="#review",
                    ),
                    WaitAgentCandidate(
                        wait_name="visual.verify.performance.and.polish",
                        label="visual.verify.performance.and.polish",
                        status="FAILED",
                        model="codex / gpt-5",
                        start_time="13:16",
                        duration="1m05s",
                        tag="#verification",
                    ),
                ],
            )
        )
        await page.expect_modal("WaitModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Wait")
        assert_page_svg_contains(page, "5m")
        assert_page_svg_contains(page, "visual.plan.revi")

        ace_png_visual.assert_page_png(
            page,
            "wait_modal_100x32",
            title="ACE wait modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
