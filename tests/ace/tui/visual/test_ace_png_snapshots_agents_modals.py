"""ACE TUI PNG visual snapshots for agent-related modals."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
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
