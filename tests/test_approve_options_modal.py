"""Tests for the approve-with-options modal."""

from textual import events
from textual.app import App, ComposeResult
from textual.keys import Keys
from textual.widgets import Switch, TextArea

from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsModal,
    ApproveOptionsResult,
)


def test_approve_options_modal_has_on_key() -> None:
    """The modal must define on_key so enter works regardless of focus."""
    assert hasattr(ApproveOptionsModal, "on_key")


def test_on_key_calls_approve_on_enter() -> None:
    """on_key with enter should call action_approve."""
    approved = False
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    def fake_approve() -> None:
        nonlocal approved
        approved = True

    modal.action_approve = fake_approve  # type: ignore[assignment]

    key_event = events.Key(Keys.Enter, character="\n")
    modal.on_key(key_event)

    assert approved


def test_on_key_ignores_non_enter() -> None:
    """on_key should not intercept keys other than enter."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_approve() -> None:
        nonlocal called
        called = True

    modal.action_approve = fake_approve  # type: ignore[assignment]

    key_event = events.Key("a", character="a")
    modal.on_key(key_event)

    assert not called


class _TestApp(App[ApproveOptionsResult | None]):
    """Minimal app for async modal tests."""

    def compose(self) -> ComposeResult:
        yield from ()


async def test_enter_approves_with_textarea_focused() -> None:
    """Enter triggers approval even when TextArea has focus (the bug)."""
    result: ApproveOptionsResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: ApproveOptionsResult | None) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Focus the TextArea (the widget that was swallowing enter)
        textarea = modal.query_one("#coder-prompt-input", TextArea)
        textarea.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)


async def test_enter_approves_with_switch_focused() -> None:
    """Enter still works when a Switch has focus (regression check)."""
    result: ApproveOptionsResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: ApproveOptionsResult | None) -> None:
            nonlocal result
            result = r

        pilot.app.push_screen(ApproveOptionsModal(), callback=on_dismiss)
        await pilot.pause()

        # Switch gets focus by default via on_mount
        focused = pilot.app.focused
        assert isinstance(focused, Switch)

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
