"""Shared one-shot ``>N`` numbered-link dispatcher coverage."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.base import FilterInput
from sase.ace.tui.modals.numbered_link_keys import (
    NUMBERED_LINK_BINDING,
    arm_numbered_link,
    clear_numbered_link_prefix,
    handle_numbered_link_key,
)


class _NumberedLinkPane(Vertical):
    BINDINGS = [
        NUMBERED_LINK_BINDING,
        ("q", "mark_close", "Close"),
        ("slash", "open_filter", "Filter"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pending_numbered_link = False
        self.followed: list[int] = []
        self.closed = False

    def compose(self) -> ComposeResult:
        yield OptionList("alpha", id="numbered-link-list")
        yield FilterInput(placeholder="Filter…", id="numbered-link-filter")

    def on_mount(self) -> None:
        self.query_one(FilterInput).display = False
        self.query_one(OptionList).focus()

    def on_key(self, event: Key) -> None:
        handle_numbered_link_key(self, event, follow=self.followed.append)

    def action_arm_numbered_link(self) -> None:
        arm_numbered_link(self)

    def action_mark_close(self) -> None:
        self.closed = True

    def action_open_filter(self) -> None:
        filt = self.query_one(FilterInput)
        filt.display = True
        filt.focus()


class _NumberedLinkApp(App[None]):
    def compose(self) -> ComposeResult:
        yield _NumberedLinkPane()

    def pane(self) -> _NumberedLinkPane:
        return self.query_one(_NumberedLinkPane)


async def test_repeated_prefix_stays_armed_then_follows() -> None:
    app = _NumberedLinkApp()
    async with app.run_test() as pilot:
        pane = app.pane()
        await pilot.press(">", ">", "2")
        assert pane.followed == [2]
        assert pane._pending_numbered_link is False


async def test_invalid_digit_cancels_without_following() -> None:
    app = _NumberedLinkApp()
    async with app.run_test() as pilot:
        pane = app.pane()
        await pilot.press(">", "0")
        await pilot.pause()
        assert pane.followed == []
        assert pane._pending_numbered_link is False

        await pilot.press(">", "1")
        assert pane.followed == [1]


async def test_non_digit_cancels_and_passthrough_keeps_other_actions() -> None:
    app = _NumberedLinkApp()
    async with app.run_test() as pilot:
        pane = app.pane()
        await pilot.press(">", "q")
        await pilot.pause()
        assert pane.followed == []
        assert pane.closed is True
        assert pane._pending_numbered_link is False


async def test_filter_input_keeps_prefix_and_digits_as_text() -> None:
    app = _NumberedLinkApp()
    async with app.run_test() as pilot:
        pane = app.pane()
        await pilot.press("slash")
        await wait_for(pilot, lambda: isinstance(app.focused, FilterInput))
        await pilot.press(">", "1", "2")
        filt = pane.query_one(FilterInput)
        assert filt.value == ">12"
        assert pane.followed == []
        assert pane._pending_numbered_link is False


async def test_pending_prefix_clears_when_hidden() -> None:
    app = _NumberedLinkApp()
    async with app.run_test() as pilot:
        pane = app.pane()
        await pilot.press(">")
        assert pane._pending_numbered_link is True
        clear_numbered_link_prefix(pane)
        await pilot.press("3")
        await pilot.pause()
        assert pane.followed == []
        assert pane._pending_numbered_link is False
