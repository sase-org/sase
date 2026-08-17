"""Tests for NotificationModal jump-hint behavior."""

from unittest.mock import MagicMock

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.notifications import Notification

from tests._notification_modal_helpers import (
    _KeyEvent,
    _TestApp,
    _make_notification,
    _wire_fake_option_list,
)


def test_notification_jump_apostrophe_without_history_highlights_first_visual() -> None:
    """A second apostrophe in jump mode navigates to the first visual row."""
    first = _make_notification("i1", action="JumpToAgent")
    second = _make_notification("i2", action="JumpToAgent")
    modal = NotificationModal([first, second])
    _wire_fake_option_list(modal, highlighted_index=1)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal.handle_jump_key("apostrophe")

    assert handled is True
    assert modal._get_selected_index() == 0
    modal._display_file.assert_called_with(first)
    modal.dismiss.assert_not_called()
    assert modal.jump_back_stack == [1]
    assert modal.jump_mode_active is False


def test_notification_jump_dispatches_uppercase_hint_character_without_dismiss() -> (
    None
):
    """Uppercase hint characters navigate to their matching notification."""
    notifications = [
        _make_notification(f"n{i:02d}", action="JumpToAgent") for i in range(37)
    ]
    modal = NotificationModal(notifications)
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    assert modal.jump_hints_by_key()[36] == "A"
    handled = modal.handle_jump_key("A")

    assert handled is True
    assert modal._get_selected_index() == 36
    modal._display_file.assert_called_with(notifications[36])
    modal.dismiss.assert_not_called()


def test_notification_jump_apostrophe_back_highlights_previous_notification() -> None:
    """Apostrophe in jump mode returns to the row on top of the back stack."""
    notifications = [
        _make_notification(f"n{i}", action="JumpToAgent") for i in range(3)
    ]
    modal = NotificationModal(notifications)
    modal._jump_state().back_stack.append(2)
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal.handle_jump_key("apostrophe")

    assert handled is True
    assert modal._get_selected_index() == 2
    modal._display_file.assert_called_with(notifications[2])
    modal.dismiss.assert_not_called()
    # A back jump pops its target instead of pushing the row it left.
    assert modal.jump_back_stack == []


def test_notification_jump_escape_cancels_without_dismiss() -> None:
    """Escape exits jump mode and leaves the notification modal open."""
    modal = NotificationModal([_make_notification("n1", action="JumpToAgent")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal.handle_jump_key("escape")

    assert handled is True
    modal.dismiss.assert_not_called()
    assert modal.jump_mode_active is False
    modal._rebuild_list.assert_called_with(highlight_index=0, show_jump_hints=False)


def test_notification_jump_invalid_key_cancels_without_changing_highlight() -> None:
    """Invalid jump keys remove hints and keep the current row highlighted."""
    notifications = [
        _make_notification(f"n{i}", action="JumpToAgent") for i in range(2)
    ]
    modal = NotificationModal(notifications)
    _wire_fake_option_list(modal, highlighted_index=1)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal.handle_jump_key("q")

    assert handled is True
    assert modal._get_selected_index() == 1
    assert modal.jump_mode_active is False
    modal.dismiss.assert_not_called()


def test_notification_jump_resets_file_index_and_refreshes_preview() -> None:
    """Jump navigation resets file paging and refreshes the target preview."""
    first = _make_notification("n1", action="JumpToAgent")
    target = _make_notification("n2", action="JumpToAgent")
    first.files = ["/tmp/one.txt"]
    target.files = ["/tmp/two.txt"]
    modal = NotificationModal([first, target])
    modal._current_file_index = 3
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal.handle_jump_key("1")

    assert handled is True
    assert modal._get_selected_index() == 1
    assert modal._current_file_index == 0
    modal._display_file.assert_called_with(target)
    modal.dismiss.assert_not_called()


def test_notification_jump_on_key_stops_valid_hint_without_dismiss() -> None:
    """The key event path consumes valid hints while keeping the modal open."""
    first = _make_notification("n1", action="JumpToAgent")
    second = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([first, second])
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]
    event = _KeyEvent(key="1", character="1")

    modal.action_jump_to_entry()
    modal.on_key(event)  # type: ignore[arg-type]

    assert event.prevented is True
    assert event.stopped is True
    assert modal._get_selected_index() == 1
    modal.dismiss.assert_not_called()


def test_notification_jump_then_enter_activates_highlighted_notification() -> None:
    """Enter remains the activation path after a jump changes highlight."""
    first = _make_notification("n1", action="JumpToAgent")
    second = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([first, second])
    option_list = _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    assert modal.handle_jump_key("1") is True
    modal.dismiss.assert_not_called()

    event = MagicMock()
    event.option = option_list.get_option_at_index(option_list.highlighted)
    modal.on_option_list_option_selected(event)

    modal.dismiss.assert_called_once_with(second)


async def test_notification_jump_pilot_keeps_modal_open_and_moves_highlight() -> None:
    """Pilot coverage for the exact apostrophe-hint modal interaction."""
    first = _make_notification("i1", action="JumpToAgent")
    second = _make_notification("i2", action="JumpToAgent")
    dismissed: list[Notification | None] = []

    async with _TestApp().run_test() as pilot:
        modal = NotificationModal([first, second], initial_index=0)
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.press("1")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert dismissed == []
        assert modal._get_selected_index() == 1


def test_notification_jump_mode_consumes_g_and_capital_g_without_scrolling() -> None:
    """Jump hints intercept g/G before the detail-pane scroll bindings see them."""
    notifications = [
        _make_notification(f"n{i}", action="JumpToAgent") for i in range(3)
    ]
    modal = NotificationModal(notifications)
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    lower_event = _KeyEvent(key="g", character="g")
    modal.on_key(lower_event)  # type: ignore[arg-type]

    assert lower_event.prevented is True
    assert lower_event.stopped is True

    modal.action_jump_to_entry()
    upper_event = _KeyEvent(key="G", character="G")
    modal.on_key(upper_event)  # type: ignore[arg-type]

    assert upper_event.prevented is True
    assert upper_event.stopped is True


def test_notification_two_character_hint_waits_and_cleans_up() -> None:
    notifications = [
        _make_notification(f"n{i:02d}", action="JumpToAgent") for i in range(63)
    ]
    modal = NotificationModal(notifications)
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    assert modal.jump_hints_by_key()[62] == "10"

    assert modal.handle_jump_key("1") is True
    assert modal.jump_mode_active is True
    assert modal._jump_state().pending_prefix == "1"
    assert modal._get_selected_index() == 0

    assert modal.handle_jump_key("0") is True
    assert modal._get_selected_index() == 62
    assert modal.jump_mode_active is False
    assert modal._jump_state().pending_prefix == ""
