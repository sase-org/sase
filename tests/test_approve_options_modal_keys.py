"""Keyboard and event-handling tests for the approve-options modal."""

from textual import events
from textual.keys import Keys
from textual.widgets import Switch

from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
)

from ._approve_options_modal_helpers import (
    ApproveOptionsApp,
    BindingsTestApp,
    EventHandlerTestApp,
)


def test_approve_options_modal_has_on_key() -> None:
    """The modal must define on_key so enter works regardless of focus."""
    assert hasattr(ApproveOptionsModal, "on_key")


def test_enter_binding_shows_tale_for_internal_approve_action() -> None:
    assert ("enter", "approve", "Tale") in ApproveOptionsModal.BINDINGS
    assert ("enter", "approve", "Approve") not in ApproveOptionsModal.BINDINGS


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
    """on_key should not call action_approve for non-enter/escape/ctrl keys."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_approve() -> None:
        nonlocal called
        called = True

    modal.action_approve = fake_approve  # type: ignore[assignment]

    key_event = events.Key("a", character="a")
    modal.on_key(key_event)

    assert not called


def test_on_key_handles_escape() -> None:
    """on_key with escape should call action_cancel."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_cancel() -> None:
        nonlocal called
        called = True

    modal.action_cancel = fake_cancel  # type: ignore[assignment]

    key_event = events.Key("escape", character=None)
    modal.on_key(key_event)

    assert called


def test_on_key_calls_edit_prompt_on_p() -> None:
    """on_key with 'p' should call action_edit_prompt."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_edit_prompt() -> None:
        nonlocal called
        called = True

    modal.action_edit_prompt = fake_edit_prompt  # type: ignore[assignment]

    key_event = events.Key("p", character="p")
    modal.on_key(key_event)

    assert called


def test_on_key_stops_printable_chars() -> None:
    """Printable chars (except space) are stopped to prevent app-level leakage."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    # 'p' is handled explicitly, test another printable char
    key_event = events.Key("a", character="a")
    modal.on_key(key_event)
    assert key_event._stop_propagation  # type: ignore[attr-defined]

    # Space must NOT be stopped (Switch needs it for toggling)
    space_event = events.Key("space", character=" ")
    modal.on_key(space_event)
    assert not space_event._stop_propagation  # type: ignore[attr-defined]


async def test_enter_approves_from_switch() -> None:
    """Enter triggers approval when a Switch has focus."""
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Switch gets focus by default via on_mount
        focused = pilot.app.focused
        assert isinstance(focused, Switch)

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)


async def test_ctrl_n_cycles_focus_forward() -> None:
    """ctrl+n should cycle focus through the two switches (no TextArea)."""
    async with ApproveOptionsApp().run_test() as pilot:
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

        # Wraps back to first
        await pilot.press("ctrl+n")
        await pilot.pause()
        wrapped = pilot.app.focused
        assert isinstance(wrapped, Switch)
        assert wrapped.id == "commit-plan-switch"


async def test_ctrl_p_cycles_focus_backward() -> None:
    """ctrl+p should cycle focus backward through the focusable widgets."""
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Navigate forward to the second switch
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert isinstance(pilot.app.focused, Switch)
        assert pilot.app.focused.id == "run-coder-switch"

        # Now go backward; should return to first switch
        await pilot.press("ctrl+p")
        await pilot.pause()
        first = pilot.app.focused
        assert isinstance(first, Switch)
        assert first.id == "commit-plan-switch"


async def test_escape_dismisses_with_switch_focused() -> None:
    """Escape must dismiss the modal when a Switch has focus."""
    dismissed = False

    async with BindingsTestApp().run_test() as pilot:

        def on_dismiss(
            _: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal dismissed
            dismissed = True

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Switch gets focus by default
        assert isinstance(pilot.app.focused, Switch)

        await pilot.press("escape")
        await pilot.pause()

        assert dismissed, "Escape did not dismiss modal when Switch had focus"


async def test_printable_chars_blocked_on_switch() -> None:
    """Printable chars on a Switch must NOT leak to the App's on_key."""
    async with EventHandlerTestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Focus stays on the commit-plan-switch (default from on_mount)
        assert isinstance(pilot.app.focused, Switch)

        pilot.app.leaked_keys.clear()
        await pilot.press("a", "j", "q")
        await pilot.pause()

        printable_leaks = [
            k for k in pilot.app.leaked_keys if len(k) == 1 and k.isprintable()
        ]
        assert not printable_leaks, (
            f"Printable chars leaked to app on_key from Switch: {printable_leaks}"
        )


def test_on_key_calls_select_model_on_m() -> None:
    """on_key with 'm' should call action_select_model."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_select_model() -> None:
        nonlocal called
        called = True

    modal.action_select_model = fake_select_model  # type: ignore[assignment]

    key_event = events.Key("m", character="m")
    modal.on_key(key_event)

    assert called
