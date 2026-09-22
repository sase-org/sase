"""sase's TUI PNG visual snapshots for agent-related modals."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    visual_agents,
    wait_for_startup,
    wait_for_state,
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


async def test_agent_workspace_tmux_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(100, 28)) as page:
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
        await page.press("m")
        await wait_for_svg_contains(page, "[x]")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Tmux Workspace")
        assert_page_svg_contains(page, "CURRENT")
        assert_page_svg_contains(page, "LINKED")
        assert_page_svg_contains(page, "sase-core")
        assert_page_svg_contains(page, "Rust backend")
        assert_page_svg_contains(page, "[x]")
        assert_page_svg_contains(page, "m mark")
        assert_page_svg_contains(page, "marked:")

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

    async with AcePage(query='"visual"', patches=patches(), size=(100, 32)) as page:
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
                        tribe="@epic",
                    ),
                    WaitAgentCandidate(
                        wait_name="visual.verify.performance.and.polish",
                        label="visual.verify.performance.and.polish",
                        status="FAILED",
                        model="codex / gpt-5",
                        start_time="13:16",
                        duration="1m05s",
                        tribe="verification",
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


async def test_wait_modal_beads_focused_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(100, 32)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        from textual.widgets import Input

        from sase.ace.tui.modals.wait_modal import WaitModal
        from sase.ace.tui.models.wait_bead_catalog import (
            WaitBeadCandidate,
            WaitBeadCatalog,
        )

        catalog = WaitBeadCatalog(
            candidates=(
                WaitBeadCandidate(
                    bead_id="sase-91.3",
                    title="Add bead picker to Wait modal",
                    status="in_progress",
                    type_label="task",
                    created_at="2026-07-01T00:00:00",
                    updated_at="2026-08-10T00:00:00",
                ),
                WaitBeadCandidate(
                    bead_id="sase-91.4",
                    title="Regenerate wait modal snapshot",
                    status="ready",
                    type_label="task",
                    created_at="2026-07-02T00:00:00",
                    updated_at="2026-08-09T00:00:00",
                ),
                WaitBeadCandidate(
                    bead_id="sase-88",
                    title="Bead store performance sweep",
                    status="open",
                    type_label="plan",
                    created_at="2026-06-01T00:00:00",
                    updated_at="2026-08-05T00:00:00",
                ),
            ),
            available=True,
        )

        modal = WaitModal(
            current_waiting_for_beads=["sase-91.3"],
            bead_project_key="visual-project",
            bead_catalog_loader=lambda project_key, **_: catalog,
        )
        page.app.push_screen(modal)
        await page.expect_modal("WaitModal")
        await wait_for_svg_contains(page, "Wait")

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        await wait_for_state(
            page,
            lambda: beads_input.has_focus,
            description="beads input focus",
        )
        # Trailing comma clears the active completion fragment so the full
        # candidate list renders, with "sase-91.3" still marked selected.
        beads_input.value = "sase-91.3, "
        await wait_for_svg_contains(page, "sase-91.4")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "sase-91.3")
        assert_page_svg_contains(page, "sase-91.4")
        assert_page_svg_contains(page, "selected")

        ace_png_visual.assert_page_png(
            page,
            "wait_modal_beads_focused_100x32",
            title="ACE wait modal beads focused",
        )


async def test_agent_action_chooser_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        from sase.ace.display_helpers import get_status_color
        from sase.ace.tui.modals.agent_action_chooser_modal import (
            AgentActionChoice,
            AgentActionChooserModal,
        )
        from sase.gate_shell.state import GATE_GLYPH
        from sase.gate_shell.status import gate_status_pair, gate_status_style

        gate_style = gate_status_style(
            gate_status_pair("TALE", None), gate_state="pending"
        )
        patch_color = get_status_color("Mailed")
        page.app.push_screen(
            AgentActionChooserModal(
                (
                    AgentActionChoice(
                        result="gate:visual123",
                        section="gate",
                        label="Review tale plan",
                        detail="sase_plan_enter_keymap.md",
                        glyph=GATE_GLYPH,
                        glyph_style=gate_style,
                        badge="TALE",
                        badge_style=gate_style,
                        age="12m",
                    ),
                    AgentActionChoice(
                        result="patch:visual",
                        section="patch",
                        label="Go to Patch",
                        detail="foo enter keymap · PR #123",
                        glyph="⎇",
                        glyph_style=patch_color,
                        badge="Mailed",
                        badge_style=patch_color,
                        age=None,
                    ),
                ),
                title="Act on visual.plan",
            )
        )
        await page.expect_modal("AgentActionChooserModal")
        await wait_for_svg_contains(page, "Act on visual.plan")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Act on visual.plan")
        assert_page_svg_contains(page, "Review tale plan")
        assert_page_svg_contains(page, "Go to Patch")
        assert_page_svg_contains(page, "GATE")
        assert_page_svg_contains(page, "PATCH")

        ace_png_visual.assert_page_png(
            page,
            "agent_action_chooser_modal_120x40",
            title="ACE agent action chooser modal",
        )
