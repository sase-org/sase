"""Behavioral coverage for the Agents deck picker modal."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.deck_picker_modal import DeckPickerModal
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.picker import (
    DeckPick,
    DeckPickerState,
    build_deck_picker_rows,
    deck_picker_heading,
)


def _modal(
    *,
    current: DeckId = DeckId.MAIN,
    close_keys: tuple[str, ...] = ("p",),
    other_hint: str | None = None,
) -> DeckPickerModal:
    state = DeckPickerState(
        panel_index=0,
        panel_label="deck",
        current=current,
        other=None,
        availability={
            DeckId.MAIN: DeckAvailability(True, 2),
            DeckId.FILES: DeckAvailability(True, 3),
            DeckId.TOOLS: DeckAvailability(False, 0),
        },
        accents={
            DeckId.MAIN: "#B48EAD",
            DeckId.FILES: "green",
            DeckId.TOOLS: "#87D7FF",
        },
    )
    return DeckPickerModal(
        build_deck_picker_rows(state),
        deck_picker_heading(state),
        close_keys,
        other_hint,
    )


def _plain(modal: DeckPickerModal, selector: str) -> str:
    return modal.query_one(selector, Static).render().plain


async def test_deck_picker_lowercase_picks_this_panel_capital_picks_other() -> None:
    for letter, deck in (("m", DeckId.MAIN), ("f", DeckId.FILES), ("t", DeckId.TOOLS)):
        for key, other_panel in ((letter, False), (letter.upper(), True)):
            results: list[DeckPick | None] = []
            async with AcePage() as page:
                page.app.push_screen(
                    _modal(other_hint="open in a new bottom panel"), results.append
                )
                await page.expect_modal("DeckPickerModal")
                await page.press(key)
                await page.expect_no_modal()
                assert results == [DeckPick(deck, other_panel)]


async def test_deck_picker_capitals_swallowed_without_other_hint() -> None:
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        page.app.push_screen(_modal(other_hint=None), results.append)
        await page.expect_modal("DeckPickerModal")

        for key in ("F", "M", "T", "J", "K", "Q"):
            await page.press(key)
            await page.pause()
            assert page.state["modal"] == "DeckPickerModal"
            assert results == []

        await page.press("f")
        await page.expect_no_modal()
        assert results == [DeckPick(DeckId.FILES, False)]


async def test_deck_picker_stray_capitals_swallowed_with_other_hint() -> None:
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        page.app.push_screen(_modal(other_hint="show in the top panel"), results.append)
        await page.expect_modal("DeckPickerModal")

        for key in ("J", "K", "Q", "X"):
            await page.press(key)
            await page.pause()
            assert page.state["modal"] == "DeckPickerModal"
            assert results == []


async def test_deck_picker_other_hint_line() -> None:
    async with AcePage() as page:
        modal = _modal(other_hint="open in a new bottom panel")
        page.app.push_screen(modal, [].append)
        await page.expect_modal("DeckPickerModal")
        assert _plain(modal, "#deck-picker-other-hint") == (
            "   M/F/T  open in a new bottom panel"
        )

    async with AcePage() as page:
        modal = _modal()
        page.app.push_screen(modal, [].append)
        await page.expect_modal("DeckPickerModal")
        assert not modal.query("#deck-picker-other-hint")


async def test_deck_picker_stray_printable_keeps_modal_open() -> None:
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        modal = _modal()
        page.app.push_screen(modal, results.append)
        await page.expect_modal("DeckPickerModal")

        await page.press("x")
        await page.pause()
        assert page.state["modal"] == "DeckPickerModal"
        assert results == []

        await page.press("f")
        await page.expect_no_modal()
        assert results == [DeckPick(DeckId.FILES, False)]


async def test_deck_picker_cancel_keys_dismiss_with_none() -> None:
    for key in ("escape", "q", "p"):
        results: list[DeckPick | None] = []
        async with AcePage() as page:
            page.app.push_screen(_modal(), results.append)
            await page.expect_modal("DeckPickerModal")
            await page.press(key)
            await page.expect_no_modal()
            assert results == [None]


async def test_deck_picker_close_key_dropped_on_collision() -> None:
    # A close key colliding with a deck letter or j/k is dropped: `m`
    # still picks Main instead of cancelling.
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        page.app.push_screen(_modal(close_keys=("m", "j")), results.append)
        await page.expect_modal("DeckPickerModal")
        await page.press("m")
        await page.expect_no_modal()
        assert results == [DeckPick(DeckId.MAIN, False)]


async def test_deck_picker_close_key_rebound_to_capital_deck_letter_dropped() -> None:
    # `pick_deck` rebound to a capital deck letter is still dropped from the
    # close keys, so `F` keeps picking Files for the other panel.
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        page.app.push_screen(
            _modal(close_keys=("F",), other_hint="show in the top panel"),
            results.append,
        )
        await page.expect_modal("DeckPickerModal")
        await page.press("F")
        await page.expect_no_modal()
        assert results == [DeckPick(DeckId.FILES, True)]


async def test_deck_picker_jk_wrap_and_enter() -> None:
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        modal = _modal()
        page.app.push_screen(modal, results.append)
        await page.expect_modal("DeckPickerModal")

        # Cursor starts on the current deck (Main, row 0).
        assert modal.query_one("#deck-picker-row-0").has_class("focused")

        # `k` wraps from the first row to the last (Tools).
        await page.press("k")
        assert modal.query_one("#deck-picker-row-2").has_class("focused")
        # `j` wraps back to the first row.
        await page.press("j")
        assert modal.query_one("#deck-picker-row-0").has_class("focused")

        await page.press("j", "j")
        assert modal.query_one("#deck-picker-row-2").has_class("focused")
        await page.press("enter")
        await page.expect_no_modal()
        assert results == [DeckPick(DeckId.TOOLS, False)]


async def test_deck_picker_row_text_and_click() -> None:
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        modal = _modal(current=DeckId.FILES)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("DeckPickerModal")
        await page.wait_for(
            lambda _screen: modal.query_one("#deck-picker-row-1").has_class("focused")
        )

        first = _plain(modal, "#deck-picker-row-0")
        assert "m" in first and "MAIN" in first and "2 cards" in first
        assert "Context, prompt, and reply" in first
        current = _plain(modal, "#deck-picker-row-1")
        assert "showing" in current

        await page.click("#deck-picker-row-2")
        await page.expect_no_modal()
        assert results == [DeckPick(DeckId.TOOLS, False)]


async def test_deck_picker_dismiss_once_guard() -> None:
    results: list[DeckPick | None] = []
    async with AcePage() as page:
        modal = _modal()
        page.app.push_screen(modal, results.append)
        await page.expect_modal("DeckPickerModal")

        await page.press("f")
        await page.expect_no_modal()
        modal.action_select_current()
        modal.action_cancel()
        assert results == [DeckPick(DeckId.FILES, False)]
