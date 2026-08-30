"""Keyboard and event-handling tests for the custom approval modal."""

from textual import events
from textual.keys import Keys

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


def test_enter_binding_chooses_current_action() -> None:
    assert ("enter", "approve", "Choose") in ApproveOptionsModal.BINDINGS
    assert ("enter", "approve", "Tale") not in ApproveOptionsModal.BINDINGS


def test_choice_bindings_are_available() -> None:
    assert ("a", "choose_approve", "Approve") in ApproveOptionsModal.BINDINGS
    assert ("t", "choose_tale", "Tale") in ApproveOptionsModal.BINDINGS
    assert ("e", "choose_epic", "Epic") in ApproveOptionsModal.BINDINGS
    assert ("w", "edit_wait", "Wait") in ApproveOptionsModal.BINDINGS


def test_on_key_calls_approve_on_enter() -> None:
    approved = False
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    def fake_approve() -> None:
        nonlocal approved
        approved = True

    modal.action_approve = fake_approve  # type: ignore[assignment]

    key_event = events.Key(Keys.Enter, character="\n")
    modal.on_key(key_event)

    assert approved


def test_on_key_selects_action_key() -> None:
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    selected: list[str] = []

    def fake_select_choice(choice: str) -> None:
        selected.append(choice)

    modal._select_choice = fake_select_choice  # type: ignore[method-assign]

    key_event = events.Key("e", character="e")
    modal.on_key(key_event)

    assert selected == ["epic"]
    assert key_event._stop_propagation  # type: ignore[attr-defined]


def test_on_key_calls_select_next_on_ctrl_n() -> None:
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    offsets: list[int] = []

    def fake_select_relative_choice(offset: int) -> None:
        offsets.append(offset)

    modal._select_relative_choice = fake_select_relative_choice  # type: ignore[method-assign]

    key_event = events.Key("ctrl+n", character=None)
    modal.on_key(key_event)

    assert offsets == [1]


def test_on_key_calls_select_previous_on_ctrl_p() -> None:
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    offsets: list[int] = []

    def fake_select_relative_choice(offset: int) -> None:
        offsets.append(offset)

    modal._select_relative_choice = fake_select_relative_choice  # type: ignore[method-assign]

    key_event = events.Key("ctrl+p", character=None)
    modal.on_key(key_event)

    assert offsets == [-1]


def test_on_key_handles_escape() -> None:
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
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_edit_prompt() -> None:
        nonlocal called
        called = True

    modal.action_edit_prompt = fake_edit_prompt  # type: ignore[assignment]

    key_event = events.Key("p", character="p")
    modal.on_key(key_event)

    assert called


def test_on_key_calls_select_model_on_m() -> None:
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_select_model() -> None:
        nonlocal called
        called = True

    modal.action_select_model = fake_select_model  # type: ignore[assignment]

    key_event = events.Key("m", character="m")
    modal.on_key(key_event)

    assert called


def test_on_key_calls_edit_wait_on_w() -> None:
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    called = False

    def fake_edit_wait() -> None:
        nonlocal called
        called = True

    modal.action_edit_wait = fake_edit_wait  # type: ignore[assignment]

    key_event = events.Key("w", character="w")
    modal.on_key(key_event)

    assert called


def test_on_key_stops_printable_chars() -> None:
    modal = ApproveOptionsModal.__new__(ApproveOptionsModal)

    key_event = events.Key("j", character="j")
    modal.on_key(key_event)
    assert key_event._stop_propagation  # type: ignore[attr-defined]

    space_event = events.Key("space", character=" ")
    modal.on_key(space_event)
    assert space_event._stop_propagation  # type: ignore[attr-defined]


async def test_enter_approves_current_choice() -> None:
    result: ApproveOptionsResult | ApproveOptionsEditPrompt | None = None

    async with ApproveOptionsApp().run_test() as pilot:

        def on_dismiss(
            r: ApproveOptionsResult | ApproveOptionsEditPrompt | None,
        ) -> None:
            nonlocal result
            result = r

        modal = ApproveOptionsModal(choice="epic")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(result, ApproveOptionsResult)
        assert result.choice == "epic"


async def test_ctrl_keys_cycle_choice() -> None:
    async with ApproveOptionsApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal._choice == "tale"
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert modal._choice == "epic"

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert modal._choice == "tale"


async def test_escape_dismisses_modal() -> None:
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

        await pilot.press("escape")
        await pilot.pause()

        assert dismissed


async def test_printable_chars_blocked_in_modal() -> None:
    async with EventHandlerTestApp().run_test() as pilot:
        modal = ApproveOptionsModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        pilot.app.leaked_keys.clear()
        await pilot.press("j", "space")
        await pilot.pause()

        printable_leaks = [
            k for k in pilot.app.leaked_keys if len(k) == 1 and k.isprintable()
        ]
        assert not printable_leaks
