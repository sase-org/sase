"""sase's TUI PNG visual snapshots for Agents Main-deck view chips."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId, DeckView
from tests.ace.tui.visual._ace_agents_deck_views_png_snapshot_shared import (
    goto_agents,
    title_plain,
    view_turn,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import show_reply_card
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _view_session(tmp_path: Path, *, extra_reply_lines: int = 0) -> Agent:
    """Build a deterministic session whose Reply auto-resolves to page blocks.

    Mirrors the deck-blocks ``paged newest`` fixture shape (plan, gate,
    monitor, then a running code turn), so the tall newest block lands the
    Main deck in block-paged AUTO.
    """
    plan = view_turn(tmp_path, "views", "plan", "--plan", 0, plan_chain_root=True)
    gate = view_turn(
        tmp_path,
        "views",
        "gate",
        "--gate",
        1,
        status="APPROVE",
        gate_id="g123abc456def",
        gate_kind="approval",
        gate_state="answered",
        gate_start_status="APPROVE",
        gate_stop_status="APPROVED",
        gate_accent="#0BCDEC",
        gate_label="Approve deploy",
    )
    monitor = view_turn(
        tmp_path,
        "views",
        "monitor",
        "--mon",
        2,
        status="MONITORED",
        monitor_id="m123abc456def",
        monitor_state="completed",
        monitor_label="just check",
        monitor_command="just check",
    )
    code = view_turn(
        tmp_path,
        "views",
        "code",
        "--code",
        3,
        extra_reply_lines=extra_reply_lines,
        status="RUNNING",
        stop_time=None,
    )
    members = [plan, gate, monitor, code]
    plan.followup_agents = members[1:]
    for member in members[1:]:
        member.agent_session_container = plan
    assert plan.is_agent_session_container_row is True
    return plan


async def _press_view(page: AcePage, detail: AgentDetail, view: DeckView) -> None:
    """Press ``P`` until the focused Main panel fixes ``view`` (toast-free)."""
    await page.press("P")
    await wait_for_state(
        page,
        lambda: detail.deck_area.panel(0).view_policy(DeckId.MAIN) is view,
        description=f"Main deck fixes {view.value}",
    )
    # Deferred Main bodies apply off the pump; wait for this generation
    # before the snapshot so pixels match the synchronous layout.
    await wait_for_state(
        page,
        lambda: (
            int(getattr(detail.deck_area.panel(0), "_main_view_applied_generation", 0))
            >= int(getattr(detail.deck_area.panel(0), "_view_generation", 0))
        ),
        description="Main deck deferred body applied",
    )
    page.app.clear_notifications()
    await wait_for_visual_idle(page)


async def test_agents_deck_view_auto_page_blocks_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        panel = detail.deck_area.panel(0)
        card = panel._main_document.card("reply")
        assert card is not None and card.has_block_navigation
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO
        title = title_plain(detail)
        assert "BLOCKS" in title or "PAGE BLOCKS" in title or " B " in f" {title} "
        assert "\U0001f512" not in title
        assert panel._block_rail_widget().has_class("-shown")
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_auto_page_blocks_120x40",
            title="ACE agents deck view auto page blocks",
        )


async def test_agents_deck_view_fixed_page_cards_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        panel = detail.deck_area.panel(0)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        # One P widens page blocks to fixed page cards.
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_CARDS
        title = title_plain(detail)
        assert "CARDS" in title or "PAGE CARDS" in title
        assert "\U0001f512" in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_fixed_page_cards_120x40",
            title="ACE agents deck view fixed page cards",
        )


async def test_agents_deck_view_fixed_spread_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        panel = detail.deck_area.panel(0)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        # Two P presses widen through page cards to locked spread.
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        await _press_view(page, detail, DeckView.SPREAD)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.SPREAD
        title = title_plain(detail)
        assert "SPREAD" in title
        assert "\U0001f512" in title
        assert "\u2503" not in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_fixed_spread_120x40",
            title="ACE agents deck view fixed spread",
        )


async def test_agents_deck_view_split_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        # Force known no-files/no-tools so the new panel duplicates Main.
        detail.deck_area.panel(0)._availability = {
            DeckId.MAIN: DeckAvailability(True, 2),
            DeckId.FILES: DeckAvailability(False, 0),
            DeckId.TOOLS: DeckAvailability(False, 0),
        }
        await page.press("vertical_line")
        await wait_for_state(
            page,
            lambda: detail.deck_area.panel(1).deck is DeckId.MAIN,
            description="Right panel duplicates the Main deck",
        )
        detail.set_deck_preferred_card(0, "reply")
        detail.set_deck_preferred_card(1, "reply")
        page.app._refresh_agents_display(list_changed=True, defer_detail=True)
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).main_view.active_card_id == "reply"
                and detail.deck_area.panel(1).main_view.active_card_id == "reply"
            ),
            description="Both panels show the Reply card",
        )
        # The new right panel takes focus; move focus back left so P fixes
        # the left panel while the right panel stays automatic.
        await page.press("ctrl+f")
        await wait_for_state(
            page,
            lambda: detail.deck_area.focused_panel().panel_index == 0,
            description="Left panel is focused",
        )
        # Fix the focused (left) panel; the right panel stays automatic.
        await page.press("P")
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).view_policy(DeckId.MAIN) is not DeckView.AUTO
            ),
            description="Left panel fixes its view",
        )
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        assert detail.deck_area.panel(1).view_policy(DeckId.MAIN) is DeckView.AUTO
        # Narrow split panels ladder down to short or tiny rungs.
        left_title = title_plain(detail, 0)
        right_title = title_plain(detail, 1)
        assert "\U0001f512" in left_title
        assert "\U0001f512" not in right_title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_split_narrow_120x40",
            title="ACE agents deck view split narrow",
        )


async def test_agents_deck_view_split_spread_paged_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        detail.deck_area.panel(0)._availability = {
            DeckId.MAIN: DeckAvailability(True, 2),
            DeckId.FILES: DeckAvailability(False, 0),
            DeckId.TOOLS: DeckAvailability(False, 0),
        }
        await page.press("vertical_line")
        await wait_for_state(
            page,
            lambda: detail.deck_area.panel(1).deck is DeckId.MAIN,
            description="Right panel duplicates the Main deck",
        )
        detail.set_deck_preferred_card(0, "reply")
        detail.set_deck_preferred_card(1, "reply")
        page.app._refresh_agents_display(list_changed=True, defer_detail=True)
        await wait_for_state(
            page,
            lambda: (
                detail.deck_area.panel(0).main_view.active_card_id == "reply"
                and detail.deck_area.panel(1).main_view.active_card_id == "reply"
            ),
            description="Both panels show the Reply card",
        )
        await page.press("ctrl+f")
        await wait_for_state(
            page,
            lambda: detail.deck_area.focused_panel().panel_index == 0,
            description="Left panel is focused",
        )
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        await _press_view(page, detail, DeckView.SPREAD)
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        left_title = title_plain(detail, 0)
        right_title = title_plain(detail, 1)
        assert (
            "SPREAD" in left_title
            or " S " in f" {left_title} "
            or "\U0001f512" in left_title
        )
        assert "\u2503" not in left_title
        # Split-narrow panels collapse the unfocused PAGE BLOCKS chip to
        # ``B  2/2``; N/M and the tiny ``B`` mark paged chrome when ┃/‹
        # do not fit.
        assert (
            "\u2503" in right_title
            or "\u2039" in right_title
            or "2/2" in right_title
            or " B " in f" {right_title} "
            or "BLOCKS" in right_title
        )
        assert "\u25b4" not in right_title and "\u25be" not in right_title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_split_spread_paged_120x40",
            title="ACE agents deck view split spread and paged",
        )


async def test_agents_deck_view_one_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.decks.card_part import context_card
    from sase.ace.tui.widgets.decks.main_document import MainDeckDocument

    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=0)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            MainDeckDocument(
                cards=(context_card(Text("only-context")),),
                subject="one-card",
                partial=False,
                digest="one-card-heading",
            ),
            "context",
        )
        await wait_for_state(
            page,
            lambda: len(panel._main_document.cards) == 1,
            description="Main deck shows one card",
        )
        panel.refresh_chrome()
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        title = title_plain(detail)
        assert "\u2503" not in title
        assert "SPREAD" not in title
        assert "PAGE" not in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_one_card_120x40",
            title="ACE agents deck view one-card heading",
        )


async def test_agents_deck_view_spread_all_in_view_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
    from sase.ace.tui.widgets.decks.main_document import MainDeckDocument

    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=0)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            MainDeckDocument(
                cards=(
                    context_card(Text("all in view context")),
                    reply_card(Text("all in view reply")),
                ),
                subject="all-in-view",
                partial=False,
                digest="all-in-view-spread",
            ),
            # Open at the first card with no scroll reserve so the whole
            # tiny deck fits the viewport: the title names the all-in-view
            # state instead of a direction.
            "context",
        )
        await wait_for_state(
            page,
            lambda: panel.is_spread(DeckId.MAIN),
            description="Main deck spreads the tiny document",
        )
        await wait_for_visual_idle(page)
        panel.refresh_chrome()
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        title = title_plain(detail)
        assert "\u2503" not in title
        assert "SPREAD" in title
        assert "in view" in title
        assert "\u25b4" not in title and "\u25be" not in title
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_spread_all_in_view_120x40",
            title="ACE agents deck view spread all in view",
        )


async def test_agents_deck_view_paged_bottom_cue_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from textual.containers import VerticalScroll

    patch_startup_loaders(
        monkeypatch,
        agents=[_view_session(tmp_path, extra_reply_lines=60)],
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_reply_card(page)
        panel = detail.deck_area.panel(0)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_BLOCKS
        # One P widens page blocks to locked page cards: "+1 card" cue.
        await _press_view(page, detail, DeckView.PAGE_CARDS)
        assert panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_CARDS
        panel.set_focused(True)
        scroll = panel.query_one("#agent-deck-panel-0-main-scroll", VerticalScroll)
        try:
            max_y = int(scroll.max_scroll_y)
        except Exception:
            max_y = 0
        if max_y > 0:
            scroll.scroll_to(y=max_y, animate=False)
        await wait_for_state(
            page,
            lambda: panel._paged_at_bottom(DeckId.MAIN) is True,
            description="Paged Main deck reaches its bottom",
        )
        page.app.clear_notifications()
        await wait_for_visual_idle(page)
        subtitle = panel._border_subtitle.plain
        assert "+1 card" in subtitle
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_view_paged_bottom_cue_120x40",
            title="ACE agents deck view paged bottom cue",
        )
