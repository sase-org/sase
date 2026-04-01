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


def test_on_key_calls_focus_next_on_ctrl_n() -> None:
    """on_key with ctrl+n should call focus_next."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_focus_next() -> None:
        nonlocal called
        called = True

    modal.focus_next = fake_focus_next  # type: ignore[assignment]

    key_event = events.Key("ctrl+n", character=None)
    modal.on_key(key_event)

    assert called


def test_on_key_calls_focus_previous_on_ctrl_p() -> None:
    """on_key with ctrl+p should call focus_previous."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_focus_previous() -> None:
        nonlocal called
        called = True

    modal.focus_previous = fake_focus_previous  # type: ignore[assignment]

    key_event = events.Key("ctrl+p", character=None)
    modal.on_key(key_event)

    assert called


def test_on_key_ignores_non_enter() -> None:
    """on_key should not intercept keys other than enter/ctrl+n/ctrl+p."""
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

    ENABLE_COMMAND_PALETTE = False

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


async def test_ctrl_n_cycles_focus_forward() -> None:
    """ctrl+n should cycle focus through the three focusable widgets."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # on_mount focuses the first switch
        first = pilot.app.focused
        assert isinstance(first, Switch)
        assert first.id == "commit-plan-switch"

        await pilot.press("ctrl+n")
        await pilot.pause()
        second = pilot.app.focused
        assert isinstance(second, Switch)
        assert second.id == "run-coder-switch"

        await pilot.press("ctrl+n")
        await pilot.pause()
        third = pilot.app.focused
        assert isinstance(third, TextArea)
        assert third.id == "coder-prompt-input"

        # Wraps back to first
        await pilot.press("ctrl+n")
        await pilot.pause()
        wrapped = pilot.app.focused
        assert isinstance(wrapped, Switch)
        assert wrapped.id == "commit-plan-switch"


async def test_ctrl_p_cycles_focus_backward() -> None:
    """ctrl+p should cycle focus backward through the focusable widgets."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Navigate forward to the second switch
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert isinstance(pilot.app.focused, Switch)
        assert pilot.app.focused.id == "run-coder-switch"

        # Now go backward — should return to first switch
        await pilot.press("ctrl+p")
        await pilot.pause()
        first = pilot.app.focused
        assert isinstance(first, Switch)
        assert first.id == "commit-plan-switch"


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
