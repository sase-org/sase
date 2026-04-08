"""Tests for the approve-with-options modal."""

from textual import events
from textual.app import App, ComposeResult
from textual.keys import Keys
from textual.screen import ModalScreen
from textual.widgets import Select, Static, Switch

from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditModel,
    ApproveOptionsEditPrompt,
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


class _TestApp(
    App[
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ]
):
    """Minimal app for async modal tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_enter_approves_from_switch() -> None:
    """Enter triggers approval when a Switch has focus."""
    result: (
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ) = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(
            r: (
                ApproveOptionsResult
                | ApproveOptionsEditPrompt
                | ApproveOptionsEditModel
                | None
            ),
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
    """ctrl+n should cycle focus through switches and model Select."""
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
        assert isinstance(third, Select)
        assert third.id == "coder-model-select"

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

        # Backward goes to first switch
        await pilot.press("ctrl+p")
        await pilot.pause()
        first = pilot.app.focused
        assert isinstance(first, Switch)
        assert first.id == "commit-plan-switch"

        # Wrapping backward reaches model select
        await pilot.press("ctrl+p")
        await pilot.pause()
        wrapped = pilot.app.focused
        assert isinstance(wrapped, Select)
        assert wrapped.id == "coder-model-select"


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


async def test_coder_off_disables_prompt_display() -> None:
    """When coder is OFF, prompt and model controls should be disabled."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        coder_sw = modal.query_one("#run-coder-switch", Switch)
        prompt_display = modal.query_one("#coder-prompt-display", Static)
        model_select = modal.query_one("#coder-model-select", Select)

        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert "disabled" in prompt_display.classes
        assert model_select.disabled is True


async def test_p_key_triggers_edit_prompt() -> None:
    """Pressing 'p' should dismiss with ApproveOptionsEditPrompt."""
    result: (
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ) = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(
            r: (
                ApproveOptionsResult
                | ApproveOptionsEditPrompt
                | ApproveOptionsEditModel
                | None
            ),
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.run_coder is True
        assert result.commit_plan is True
        assert result.coder_prompt == ""


async def test_p_key_no_op_when_coder_off() -> None:
    """Pressing 'p' when coder is OFF should not dismiss the modal."""
    dismissed = False

    async with _TestApp().run_test() as pilot:

        def on_dismiss(
            _: (
                ApproveOptionsResult
                | ApproveOptionsEditPrompt
                | ApproveOptionsEditModel
                | None
            ),
        ) -> None:
            nonlocal dismissed
            dismissed = True

        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Turn coder OFF
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        coder_sw.focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert not coder_sw.value

        # Press p — should be no-op
        await pilot.press("p")
        await pilot.pause()

        assert not dismissed


async def test_initial_state_restoration() -> None:
    """Constructor params should restore switch and prompt state."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal(
            commit_plan=False,
            run_coder=True,
            coder_prompt="do the thing",
            coder_model="codex/o3",
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        commit_sw = modal.query_one("#commit-plan-switch", Switch)
        coder_sw = modal.query_one("#run-coder-switch", Switch)
        prompt_display = modal.query_one("#coder-prompt-display", Static)
        model_select = modal.query_one("#coder-model-select", Select)

        assert commit_sw.value is False
        assert coder_sw.value is True
        display_text = str(prompt_display.render())
        assert "do the thing" in display_text
        assert model_select.value == "codex/o3"


async def test_p_key_preserves_state_in_edit_prompt() -> None:
    """ApproveOptionsEditPrompt should carry current switch + prompt state."""
    result: (
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ) = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(
            r: (
                ApproveOptionsResult
                | ApproveOptionsEditPrompt
                | ApproveOptionsEditModel
                | None
            ),
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(
            commit_plan=False,
            run_coder=True,
            coder_prompt="existing prompt",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditPrompt)
        assert result.commit_plan is False
        assert result.run_coder is True
        assert result.coder_prompt == "existing prompt"


async def test_selecting_custom_model_dismisses_with_edit_model() -> None:
    """Selecting Custom... should dismiss with ApproveOptionsEditModel."""
    result: (
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ) = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(
            r: (
                ApproveOptionsResult
                | ApproveOptionsEditPrompt
                | ApproveOptionsEditModel
                | None
            ),
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(coder_model="codex/o3")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        model_select = modal.query_one("#coder-model-select", Select)
        model_select.value = "__custom_model__"
        await pilot.pause()

        assert isinstance(result, ApproveOptionsEditModel)
        assert result.coder_model == "codex/o3"


async def test_long_prompt_truncated_in_display() -> None:
    """Long prompts should be truncated with ... in the display."""
    async with _TestApp().run_test() as pilot:
        long_prompt = "a" * 100
        modal = ApproveOptionsModal(coder_prompt=long_prompt)
        pilot.app.push_screen(modal)
        await pilot.pause()

        prompt_display = modal.query_one("#coder-prompt-display", Static)
        display_text = str(prompt_display.render())
        assert "..." in display_text
        assert len(display_text) < len(long_prompt)


async def test_empty_prompt_shows_none() -> None:
    """Empty prompt should display 'none'."""
    async with _TestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        prompt_display = modal.query_one("#coder-prompt-display", Static)
        display_text = str(prompt_display.render())
        assert "none" in display_text


# ---------------------------------------------------------------------------
# Phase 1 — Diagnostic tests (realistic AceApp environment)
# ---------------------------------------------------------------------------


class _BindingsTestApp(
    App[
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ],
):
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


class _EventHandlerTestApp(
    App[
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ],
):
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


async def test_escape_dismisses_with_switch_focused() -> None:
    """Escape must dismiss the modal when a Switch has focus."""
    dismissed = False

    async with _BindingsTestApp().run_test() as pilot:

        def on_dismiss(
            _: (
                ApproveOptionsResult
                | ApproveOptionsEditPrompt
                | ApproveOptionsEditModel
                | None
            ),
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
