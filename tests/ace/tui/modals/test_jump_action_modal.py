"""Tests for the jump action chooser modal."""

from __future__ import annotations

from typing import cast

from textual.app import App, ComposeResult

from sase.ace.tui.modals.jump_action_modal import JumpActionModal, JumpChoice


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _modal(choices: list[str]) -> JumpActionModal:
    return JumpActionModal(
        title="#review",
        kind_label="xprompt",
        icon="#",
        source_display="/tmp/review.md:4:1",
        choices=cast(list[JumpChoice], choices),
    )


async def test_jump_action_modal_returns_available_choice() -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_modal(["tmux", "editor", "load"]), on_dismiss)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()

    assert result == "load"


async def test_jump_action_modal_ignores_unavailable_choice() -> None:
    dismissed: list[object] = []

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(_modal(["editor"]), dismissed.append)
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()

        assert dismissed == []
        assert len(pilot.app.screen_stack) == 2

        await pilot.press("e")
        await pilot.pause()

    assert dismissed == ["editor"]


async def test_jump_action_modal_cancel_returns_none() -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_modal(["editor"]), on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert result is None
