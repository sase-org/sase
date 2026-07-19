"""ACE TUI PNG visual snapshots for agent-related modals."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import AgentCleanupClanModal
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    visual_agents,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _cleanup_clan_member(
    name: str,
    suffix: str,
    *,
    clan: str,
    status: str,
    pid: int | None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/workspace/sase/visual_project.sase",
        status=status,
        start_time=datetime(2026, 7, 6, 11, 15, 0),
        run_start_time=datetime(2026, 7, 6, 11, 15, 0),
        stop_time=(datetime(2026, 7, 6, 11, 45, 0) if status != "RUNNING" else None),
        raw_suffix=suffix,
        agent_name=name,
        tribe="epic",
        pid=pid,
        agent_clan=clan,
        agent_clan_generation=f"{clan}-generation",
    )


def _cleanup_clan_modal() -> AgentCleanupClanModal:
    members = [
        _cleanup_clan_member(
            "sase-74.plan",
            "sase-74-plan",
            clan="sase-74",
            status="RUNNING",
            pid=101,
        ),
        _cleanup_clan_member(
            "sase-74.polish",
            "sase-74-polish",
            clan="sase-74",
            status="DONE",
            pid=None,
        ),
        _cleanup_clan_member(
            "sase-72.verify",
            "sase-72-verify",
            clan="sase-72",
            status="FAILED",
            pid=None,
        ),
    ]
    rows = project_clan_tree(members)
    clans = [row for row in rows if row.is_clan_container]
    targets = [row for row in rows if not row.is_clan_container]
    return AgentCleanupClanModal(
        clans=clans,
        targets=targets,
        focused_panel_label="@epic",
        initial_clan=("sase-74", "sase-74-generation"),
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
        await wait_for_svg_contains(page, "Auto-Approve")
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
        await wait_for_svg_contains(page, "Tmux Workspace")
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
                        tag="@review",
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
        await wait_for_svg_contains(page, "visual.plan.revi")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Wait")
        assert_page_svg_contains(page, "5m")
        assert_page_svg_contains(page, "visual.plan.revi")

        ace_png_visual.assert_page_png(
            page,
            "wait_modal_100x32",
            title="ACE wait modal",
        )


async def test_agent_cleanup_clan_modal_png_snapshot(
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

        page.app.push_screen(_cleanup_clan_modal())
        await page.expect_modal("AgentCleanupClanModal")
        await page.press("l", "j", "space")
        await wait_for_svg_contains(page, "Selected:")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Clan Cleanup")
        assert_page_svg_contains(page, "sase-74")
        assert_page_svg_contains(page, "Selected:")
        assert_page_svg_contains(page, "1 member")
        assert_page_svg_contains(page, "kill 1")

        ace_png_visual.assert_page_png(
            page,
            "agent_cleanup_clan_modal_partial_100x32",
            title="ACE clan cleanup chooser with partial selection",
        )
