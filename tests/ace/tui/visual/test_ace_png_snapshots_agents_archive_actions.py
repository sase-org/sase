"""ACE PNG snapshots for Archive marks, restore overlays, and the chooser."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_archive_png_snapshot_shared import (
    NOW,
    inbox_agent,
    list_history,
    open_archive,
    settle_archive_detail,
    wait_for_svg,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_archive_marked_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A marked Archive run draws the Inbox mark style."""
    from sase.ace.tui.actions.agents._archive_actions import archive_marked_run_keys

    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        await page.press("m")
        assert len(archive_marked_run_keys(page.app)) == 1
        await settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "[✓]")
        assert_page_svg_contains(page, "unmark (1)")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_marked_120x40",
            title="ACE Agents Archive marked row",
        )


async def test_archive_restored_overlay_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restored Archive row renders the restore overlay chip."""
    from sase.ace.tui.actions.agents._archive_view import mark_archive_row_restored

    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        selected = page.app._agents_archive_view.archive.selected_key
        assert selected is not None and "@" in selected
        mark_archive_row_restored(page.app, selected)
        await settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "⌂ restored")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_restored_120x40",
            title="ACE Agents Archive restored overlay",
        )


async def test_archive_restored_row_with_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Archive restore paints the dimmed row with its single toast."""
    from textual.widgets._toast import Toast

    from sase.ace.tui.actions.agents._archive_restore import run_archive_restore
    from tests.ace.tui.visual._ace_png_snapshot_helpers import stabilize_toast_frame

    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(
        initial_tab="agents", size=(120, 40), notifications=True
    ) as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        selected = page.app._agents_archive_view.archive.selected_key
        assert selected is not None and "@" in selected
        agent = SimpleNamespace(
            identity=("agent", "today.done", None),
            agent_name="today.done",
            display_name="today.done",
        )
        monkeypatch.setattr(
            "sase.ace.tui.actions.agents._archive_reader._load_archive_bundle",
            lambda _owner, _row: {"unreadable": False, "agent": agent},
        )
        monkeypatch.setattr(
            page.app,
            "_do_revive_agents",
            lambda agents: SimpleNamespace(failed=[]),
        )
        summary = run_archive_restore(page.app)
        assert [name for _key, name in summary.restored] == ["today.done"]
        await page.wait_for(
            lambda _state: bool(list(page.app.screen.query(Toast))), timeout=15.0
        )
        await wait_for_svg(page, "is back in the inbox")
        await settle_archive_detail(page)
        await wait_for_visual_idle(page)
        await stabilize_toast_frame(page)
        assert_page_svg_contains(page, "⌂ restored")
        assert_page_svg_contains(page, "is back in the inbox")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_restored_toast_120x40",
            title="ACE Agents Archive restored row with toast",
        )


def _archive_chooser_choices(*, marked: int = 0) -> tuple[Any, ...]:
    from sase.ace.tui.actions.agents._archive_restore_types import (
        CHOICE_COPY_MORE,
        CHOICE_COPY_REF,
        CHOICE_FORK,
        CHOICE_OPEN_CHAT,
        CHOICE_RESTORE,
        CHOICE_RESTORE_SHOW,
    )
    from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChoice

    restore_label = f"Restore {marked} marked" if marked else "Restore to inbox"
    return (
        AgentActionChoice(
            result=CHOICE_RESTORE,
            section="archive",
            label=restore_label,
            detail="shows it again · starts no new run",
            glyph="⌂",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="r",
        ),
        AgentActionChoice(
            result=CHOICE_RESTORE_SHOW,
            section="archive",
            label="Restore and show in inbox",
            detail="reveals the agent in the Inbox",
            glyph="⌂",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="s",
        ),
        AgentActionChoice(
            result=CHOICE_FORK,
            section="archive",
            label="Fork into a new agent",
            detail="starts a new run from this one",
            glyph="⑂",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="F",
        ),
        AgentActionChoice(
            result=CHOICE_OPEN_CHAT,
            section="read",
            label="Open chat in $EDITOR",
            detail="read-only",
            glyph="▤",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="e",
        ),
        AgentActionChoice(
            result=CHOICE_COPY_REF,
            section="read",
            label="Copy @agent reference",
            detail=None,
            glyph="@",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="y",
        ),
        AgentActionChoice(
            result=CHOICE_COPY_MORE,
            section="read",
            label="More copy targets",
            detail=None,
            glyph="%",
            glyph_style="",
            badge=None,
            badge_style=None,
            age=None,
            hotkey="%",
        ),
    )


async def test_archive_chooser_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive chooser paints ARCHIVE then READ without marks."""
    from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChooserModal

    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents", size=(120, 40)) as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())
        page.app.push_screen(
            AgentActionChooserModal(
                _archive_chooser_choices(),
                title="Act on bob-cli-5p.4 · archived",
            )
        )
        await page.expect_modal("AgentActionChooserModal")
        await wait_for_svg(page, "Act on bob-cli-5p.4")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "ARCHIVE")
        assert_page_svg_contains(page, "READ")
        assert_page_svg_contains(page, "Restore to inbox")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_chooser_120x40",
            title="ACE Agents Archive chooser",
        )


async def test_archive_chooser_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive chooser paints Restore N marked when marks exist."""
    from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChooserModal

    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents", size=(120, 40)) as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())
        page.app.push_screen(
            AgentActionChooserModal(
                _archive_chooser_choices(marked=2),
                title="Act on bob-cli-5p.4 · archived",
            )
        )
        await page.expect_modal("AgentActionChooserModal")
        await wait_for_svg(page, "Restore 2 marked")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "ARCHIVE")
        assert_page_svg_contains(page, "READ")
        assert_page_svg_contains(page, "Restore 2 marked")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_chooser_marked_120x40",
            title="ACE Agents Archive chooser with marks",
        )
