"""Tests for the approve-with-options modal."""

from textual import events
from textual.app import App, ComposeResult
from textual.keys import Keys
from textual.screen import ModalScreen
from textual.widgets import Static, Switch, TextArea

from sase.ace.tui.bindings import DEFAULT_BINDINGS
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


def test_on_key_stops_printable_chars() -> None:
    """Printable chars (except space) are stopped to prevent app-level leakage."""
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    key_event = events.Key("a", character="a")
    modal.on_key(key_event)
    assert key_event._stop_propagation  # type: ignore[attr-defined]

    # Space must NOT be stopped (Switch needs it for toggling)
    space_event = events.Key("space", character=" ")
    modal.on_key(space_event)
    assert not space_event._stop_propagation  # type: ignore[attr-defined]


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


async def test_toggle_coder_off_locks_commit_on() -> None:
    """Turning off coder locks commit switch (at least one must be ON)."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        commit_lbl = modal.query_one("#commit-plan-label", Static)

        # Toggle coder OFF via space on the switch
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert not coder_sw.value
        assert commit_sw.value is True
        assert commit_sw.disabled is True
        assert "locked" in commit_lbl.classes
        assert "(required)" in str(commit_lbl.render())


async def test_toggle_commit_off_locks_coder_on() -> None:
    """Turning off commit locks coder switch (at least one must be ON)."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        coder_lbl = modal.query_one("#run-coder-label", Static)

        # Toggle commit OFF
        commit_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert not commit_sw.value
        assert coder_sw.value is True
        assert coder_sw.disabled is True
        assert "locked" in coder_lbl.classes
        assert "(required)" in str(coder_lbl.render())


async def test_toggle_back_on_unlocks_other() -> None:
    """Toggling a switch back ON re-enables the other switch."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)

        # Toggle coder OFF, then back ON
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert commit_sw.disabled is False
        assert coder_sw.disabled is False
        assert coder_sw.value is True


async def test_coder_off_disables_prompt() -> None:
    """When coder is OFF, prompt area should be disabled."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        coder_sw = modal.query_one("#run-coder-switch", Switch)
        prompt = modal.query_one("#coder-prompt-input", TextArea)

        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert prompt.disabled is True


async def test_typing_in_textarea_inserts_characters() -> None:
    """Printable characters typed with TextArea focused must be inserted."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        textarea = modal.query_one("#coder-prompt-input", TextArea)
        textarea.focus()
        await pilot.pause()

        await pilot.press("a", "b", "c")
        await pilot.pause()

        assert textarea.text == "abc"


async def test_typing_q_inserts_instead_of_dismissing() -> None:
    """Typing 'q' in the TextArea must insert 'q', NOT dismiss the modal."""
    dismissed = False

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_: ApproveOptionsResult | None) -> None:
            nonlocal dismissed
            dismissed = True

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        textarea = modal.query_one("#coder-prompt-input", TextArea)
        textarea.focus()
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()

        assert not dismissed, "Modal was dismissed by 'q' — binding conflict!"
        assert textarea.text == "q"


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


# ---------------------------------------------------------------------------
# Phase 1 — Diagnostic tests (realistic AceApp environment)
# ---------------------------------------------------------------------------


class _BindingsTestApp(App[ApproveOptionsResult | None]):
    """Test app with AceApp-like single-character bindings (H1 diagnostic)."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = DEFAULT_BINDINGS

    def compose(self) -> ComposeResult:
        yield from ()

    def check_action(
        self, action: str, parameters: tuple[object, ...] = ()
    ) -> bool | None:
        """Simulate AceApp where all action methods exist."""
        return True


class _StackedFirstModal(ModalScreen[None]):
    """Minimal modal used as the bottom layer for stacking diagnostics."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Static("First modal placeholder")

    def action_cancel(self) -> None:
        self.dismiss(None)


class _EventHandlerTestApp(App[ApproveOptionsResult | None]):
    """Test app with EventHandlersMixin-like on_key (H3 diagnostic)."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = DEFAULT_BINDINGS

    def __init__(self) -> None:
        super().__init__()
        self._custom_mode_prefixes: dict[str, str] = {}
        self.leaked_keys: list[str] = []

    def compose(self) -> ComposeResult:
        yield from ()

    def check_action(
        self, action: str, parameters: tuple[object, ...] = ()
    ) -> bool | None:
        return True

    def on_key(self, event: events.Key) -> None:
        """Mimics EventHandlersMixin.on_key — records keys that reach the app."""
        self.leaked_keys.append(event.key)
        if event.key in self._custom_mode_prefixes:
            event.prevent_default()
            event.stop()


async def test_escape_dismisses_with_textarea_focused() -> None:
    """Escape must dismiss the modal even when TextArea has focus."""
    dismissed = False

    async with _BindingsTestApp().run_test() as pilot:

        def on_dismiss(_: ApproveOptionsResult | None) -> None:
            nonlocal dismissed
            dismissed = True

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Navigate to TextArea
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        textarea = modal.query_one("#coder-prompt-input", TextArea)
        assert pilot.app.focused is textarea

        await pilot.press("escape")
        await pilot.pause()

        assert dismissed, "Escape did not dismiss modal when TextArea had focus"


async def test_printable_chars_blocked_on_switch() -> None:
    """Printable chars on a Switch must NOT leak to the App's on_key."""
    async with _EventHandlerTestApp().run_test() as pilot:
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


async def test_diag_typing_with_app_bindings() -> None:
    """H1: Typing in TextArea must work when app has AceApp-level bindings."""
    async with _BindingsTestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Navigate: commit-switch → coder-switch → textarea
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        textarea = modal.query_one("#coder-prompt-input", TextArea)
        assert pilot.app.focused is textarea, (
            f"Expected TextArea focus, got {type(pilot.app.focused).__name__}"
        )

        await pilot.press("a", "b", "c")
        await pilot.pause()

        assert textarea.text == "abc", (
            f"H1 CONFIRMED: Typing failed with app bindings. Got {textarea.text!r}"
        )


async def test_diag_typing_with_stacked_modals() -> None:
    """H2: Typing in TextArea must work when stacked on another ModalScreen."""
    async with _BindingsTestApp().run_test() as pilot:
        pilot.app.push_screen(_StackedFirstModal())
        await pilot.pause()

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Navigate to TextArea
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        textarea = modal.query_one("#coder-prompt-input", TextArea)
        assert pilot.app.focused is textarea, (
            f"Expected TextArea focus, got {type(pilot.app.focused).__name__}"
        )

        await pilot.press("a", "b", "c")
        await pilot.pause()

        assert textarea.text == "abc", (
            f"H2 CONFIRMED: Typing failed with stacked modals. Got {textarea.text!r}"
        )


async def test_diag_typing_with_event_handler_on_key() -> None:
    """H3: Printable chars must not leak to app on_key when TextArea has focus."""
    async with _EventHandlerTestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Navigate to TextArea
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()

        textarea = modal.query_one("#coder-prompt-input", TextArea)
        assert pilot.app.focused is textarea

        pilot.app.leaked_keys.clear()
        await pilot.press("a", "b", "c")
        await pilot.pause()

        assert textarea.text == "abc", (
            f"H3 CONFIRMED (no insertion): Typing failed. Got {textarea.text!r}"
        )
        printable_leaks = [
            k for k in pilot.app.leaked_keys if len(k) == 1 and k.isprintable()
        ]
        assert not printable_leaks, (
            f"H3 CONFIRMED (leakage): Keys leaked to app on_key: {printable_leaks}"
        )
