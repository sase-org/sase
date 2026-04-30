"""Tests for NotificationModal dismiss behavior."""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.notifications import Notification


def _make_notification(notification_id: str, action: str | None = None) -> Notification:
    """Create a minimal notification object for modal tests."""
    return Notification(
        id=notification_id,
        timestamp="2026-03-17T12:00:00-04:00",
        sender="test",
        action=action,
    )


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _FakeOptionList:
    def __init__(self, options: list[Any]) -> None:
        self.options = list(options)
        self.highlighted: int | None = None

    @property
    def option_count(self) -> int:
        return len(self.options)

    def get_option_at_index(self, row: int) -> Any:
        return self.options[row]

    def clear_options(self) -> None:
        self.options.clear()

    def add_option(self, option: Any) -> None:
        self.options.append(option)

    def add_class(self, _class_name: str) -> None:
        return


class _KeyEvent:
    def __init__(self, key: str, character: str | None) -> None:
        self.key = key
        self.character = character
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


def _wire_fake_option_list(
    modal: NotificationModal, *, highlighted_index: int = 0
) -> _FakeOptionList:
    option_list = _FakeOptionList(modal._create_sectioned_options())
    row = modal._row_for_notification_index(  # type: ignore[arg-type]
        option_list, highlighted_index
    )
    option_list.highlighted = row

    def query_one(selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#notification-list":
            return option_list
        raise LookupError(selector)

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    return option_list


def test_dismiss_notification_direct_for_non_plan_question() -> None:
    """x should dismiss non-plan/question notifications immediately."""
    modal = NotificationModal([_make_notification("n1", action="JumpToAgent")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_called_once_with("n1")
    assert modal._pending_confirm_notification_id is None
    assert modal._notifications == []
    modal._rebuild_list.assert_called_once_with(highlight_index=None)


def test_dismiss_notification_requires_confirmation_for_plan_question() -> None:
    """x should require y/n confirmation for plan/question notifications."""
    modal = NotificationModal([_make_notification("n1", action="PlanApproval")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    assert modal._pending_confirm_notification_id == "n1"
    assert len(modal._notifications) == 1
    modal.notify.assert_called_once_with("Dismiss plan/question notification? (y/n)")


def test_confirm_dismiss_notification_dismisses_pending_item() -> None:
    """y should dismiss the pending plan/question notification."""
    modal = NotificationModal([_make_notification("n1", action="UserQuestion")])
    modal._pending_confirm_notification_id = "n1"
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_confirm_dismiss_notification()

    mock_mark.assert_called_once_with("n1")
    assert modal._pending_confirm_notification_id is None
    assert modal._notifications == []
    modal._rebuild_list.assert_called_once_with(highlight_index=None)


def test_dismiss_highlights_next_notification_in_visual_order() -> None:
    """Dismiss picks the next visible row, not the next raw-list index."""
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True
    priority = _make_notification("p1", action="PlanApproval")
    modal = NotificationModal([inbox, muted, priority])
    modal._pending_confirm_notification_id = "p1"
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_confirm_dismiss_notification()

    mock_mark.assert_called_once_with("p1")
    assert [notification.id for notification in modal._notifications] == ["i1", "m1"]
    modal._rebuild_list.assert_called_once_with(highlight_index=0)


def test_dismiss_final_visible_notification_highlights_previous_visual_row() -> None:
    """Dismissing the final visible row falls back to the previous visible row."""
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True
    priority = _make_notification("p1", action="PlanApproval")
    inbox = _make_notification("i1", action="JumpToAgent")
    modal = NotificationModal([muted, priority, inbox])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_called_once_with("m1")
    assert [notification.id for notification in modal._notifications] == ["p1", "i1"]
    modal._rebuild_list.assert_called_once_with(highlight_index=1)


def test_toggle_mute_sets_muted_and_rebuilds() -> None:
    """m should toggle mute state, persist via mark_muted, and rebuild."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with("n1", True)
    assert notification.muted is True
    modal._rebuild_list.assert_called_once_with(highlight_index=0)
    modal.notify.assert_called_once_with("Muted")


def test_toggle_mute_unmutes_when_already_muted() -> None:
    """m on an already-muted notification flips it back to unmuted."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with("n1", False)
    assert notification.muted is False
    modal.notify.assert_called_once_with("Unmuted")


def test_styled_label_uses_tilde_prefix_for_muted() -> None:
    """A muted notification renders with '~ ' prefix instead of '* '."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert label.plain.startswith("~ ")


def test_styled_label_uses_asterisk_for_unread_unmuted() -> None:
    """An unread non-muted notification keeps the gold '* ' prefix."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert label.plain.startswith("* ")


def test_press_s_pushes_snooze_picker_and_passes_callback() -> None:
    """``s`` pushes the SnoozeDurationModal and registers a callback."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]

    push_screen = MagicMock()
    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.push_screen = push_screen
        modal.action_snooze()

    push_screen.assert_called_once()
    pushed_modal, kwargs = push_screen.call_args
    from sase.ace.tui.modals.snooze_duration_modal import SnoozeDurationModal

    assert isinstance(pushed_modal[0], SnoozeDurationModal)
    assert "callback" in kwargs


def test_snooze_callback_with_timedelta_calls_mark_snoozed() -> None:
    """A timedelta from the picker is converted to an absolute datetime."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        modal.action_snooze()

        assert captured_callback, "callback was not registered"
        callback = captured_callback[0]
        callback(timedelta(minutes=15))

        mock_mark.assert_called_once()
        args, _ = mock_mark.call_args

    assert args[0] == "n1"
    assert isinstance(args[1], datetime)
    assert notification.muted is True
    assert notification.snooze_until == args[1].isoformat()
    modal.notify.assert_called_once_with("Snoozed for 15m")


def test_snooze_callback_with_datetime_uses_until_label() -> None:
    """A datetime result (e.g. tomorrow morning) preserves the absolute time."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    target = datetime(2026, 4, 22, 9, 0, 0)
    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        modal.action_snooze()
        captured_callback[0](target)

        mock_mark.assert_called_once_with("n1", target)

    assert notification.snooze_until == target.isoformat()
    modal.notify.assert_called_once_with("Snoozed until tomorrow morning")


def test_snooze_callback_none_is_cancellation() -> None:
    """Picker returning None just toasts 'Snooze cancelled' — no store call."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    captured_callback: list = []

    def fake_push_screen(_screen, *, callback) -> None:
        captured_callback.append(callback)

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch("sase.ace.tui.modals.notification_modal.mark_snoozed") as mock_mark,
    ):
        mock_app.push_screen = fake_push_screen
        modal.action_snooze()
        captured_callback[0](None)

        mock_mark.assert_not_called()

    assert notification.snooze_until is None
    assert notification.muted is False
    modal.notify.assert_called_once_with("Snooze cancelled")


def test_unmute_on_snoozed_clears_snooze_and_toasts() -> None:
    """``m`` on a snoozed row unmutes AND clears snooze_until."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    notification.snooze_until = "2026-04-22T09:00:00-04:00"
    modal = NotificationModal([notification])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_called_once_with("n1", False)
    assert notification.muted is False
    assert notification.snooze_until is None
    modal.notify.assert_called_once_with("Unmuted (snooze cancelled)")


def test_styled_label_includes_snooze_badge_when_snoozed() -> None:
    """A snoozed row's label appends a '⏰ {time}' badge."""
    from datetime import datetime as _datetime
    from datetime import timedelta as _timedelta

    from sase.core.time import get_timezone

    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    deadline = _datetime.now(get_timezone()) + _timedelta(minutes=14)
    notification.snooze_until = deadline.isoformat()

    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert "⏰" in label.plain


def test_cancel_dismiss_notification_clears_pending() -> None:
    """n should cancel pending dismissal and keep the notification."""
    modal = NotificationModal([_make_notification("n1", action="PlanApproval")])
    modal._pending_confirm_notification_id = "n1"
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_cancel_dismiss_notification()

    mock_mark.assert_not_called()
    assert modal._pending_confirm_notification_id is None
    assert len(modal._notifications) == 1
    modal.notify.assert_called_once_with("Dismiss canceled")


def test_sections_render_in_priority_inbox_muted_order() -> None:
    """Options appear in PRIORITY → INBOX → MUTED order, with header rows."""
    priority = _make_notification("p1", action="PlanApproval")
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True

    modal = NotificationModal([priority, inbox, muted])
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert ids == ["hdr:priority", "0", "hdr:inbox", "1", "hdr:muted", "2"]


def test_visual_notification_index_order_skips_section_headers() -> None:
    """Visual index order contains only selectable notification rows."""
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True
    priority = _make_notification("p1", action="PlanApproval")

    modal = NotificationModal([inbox, muted, priority])

    assert modal._visual_notification_index_order() == [2, 0, 1]


def test_empty_section_header_not_rendered() -> None:
    """Sections with no items emit no header row."""
    modal = NotificationModal(
        [
            _make_notification("i1", action="JumpToAgent"),
            _make_notification("i2", action="JumpToAgent"),
        ]
    )
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert "hdr:priority" not in ids
    assert "hdr:muted" not in ids
    assert ids == ["hdr:inbox", "0", "1"]


def test_header_options_are_disabled() -> None:
    """Header rows are added with disabled=True so cursor nav skips them."""
    inbox = _make_notification("i1", action="JumpToAgent")
    modal = NotificationModal([inbox])
    options = modal._create_sectioned_options()

    headers = [opt for opt in options if str(opt.id).startswith("hdr:")]
    assert headers, "expected at least one header row"
    assert all(opt.disabled for opt in headers)
    notif_options = [opt for opt in options if not str(opt.id).startswith("hdr:")]
    assert all(not opt.disabled for opt in notif_options)


def test_get_selected_index_returns_none_for_header() -> None:
    """_get_selected_index returns None when the highlighted row is a header."""
    modal = NotificationModal([_make_notification("i1", action="JumpToAgent")])

    fake_option = MagicMock()
    fake_option.id = "hdr:inbox"
    fake_list = MagicMock()
    fake_list.highlighted = 0
    fake_list.get_option_at_index.return_value = fake_option
    modal.query_one = MagicMock(return_value=fake_list)  # type: ignore[method-assign]

    assert modal._get_selected_index() is None


def test_dismiss_no_ops_when_highlight_on_header() -> None:
    """Action dismiss is a no-op when _get_selected_index returns None."""
    modal = NotificationModal([_make_notification("i1", action="JumpToAgent")])
    modal._get_selected_index = lambda: None  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    modal._rebuild_list.assert_not_called()
    assert len(modal._notifications) == 1


def test_toggle_mute_no_ops_when_highlight_on_header() -> None:
    """Action toggle_mute is a no-op when _get_selected_index returns None."""
    modal = NotificationModal([_make_notification("i1", action="JumpToAgent")])
    modal._get_selected_index = lambda: None  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_not_called()
    modal._rebuild_list.assert_not_called()


def test_muted_priority_lives_in_muted_section() -> None:
    """A priority-typed notification that is muted ends up under MUTED, not PRIORITY."""
    n = _make_notification("p1", action="PlanApproval")
    n.muted = True
    modal = NotificationModal([n])

    assert modal._section_for(n) == "muted"

    options = modal._create_sectioned_options()
    ids = [opt.id for opt in options]
    assert "hdr:priority" not in ids
    assert ids == ["hdr:muted", "0"]


def test_section_for_inbox() -> None:
    """A non-priority, non-muted notification lands in INBOX."""
    n = _make_notification("i1", action="JumpToAgent")
    modal = NotificationModal([n])
    assert modal._section_for(n) == "inbox"


def test_section_for_priority() -> None:
    """A priority-typed unmuted notification lands in PRIORITY."""
    n = _make_notification("p1", action="PlanApproval")
    modal = NotificationModal([n])
    assert modal._section_for(n) == "priority"


def test_header_text_includes_label_and_count() -> None:
    """The header text contains the section label and ' · N' count."""
    text = NotificationModal._build_header_text("priority", 3)
    assert "PRIORITY" in text.plain
    assert "· 3" in text.plain


def test_jump_hints_render_only_on_notification_rows_in_visual_order() -> None:
    """Jump markers are assigned to selectable rows, not section headers."""
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True
    priority = _make_notification("p1", action="PlanApproval")

    modal = NotificationModal([inbox, muted, priority])
    hints = {2: "1", 0: "2", 1: "3"}
    options = modal._create_sectioned_options(jump_hints=hints)

    by_id = {str(option.id): str(option.prompt) for option in options}
    assert "[1]" not in by_id["hdr:priority"]
    assert "[2]" not in by_id["hdr:inbox"]
    assert "[3]" not in by_id["hdr:muted"]
    assert "[1]" in by_id["2"]
    assert "[2]" in by_id["0"]
    assert "[3]" in by_id["1"]


def test_notification_jump_apostrophe_without_history_highlights_first_visual() -> None:
    """A second apostrophe in jump mode navigates to the first visual row."""
    inbox = _make_notification("i1", action="JumpToAgent")
    priority = _make_notification("p1", action="PlanApproval")
    modal = NotificationModal([inbox, priority])
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert modal._get_selected_index() == 1
    modal._display_file.assert_called_with(priority)
    modal.dismiss.assert_not_called()
    assert modal._entry_jump_last_index == 0
    assert modal._entry_jump_mode_active is False


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
    assert modal._entry_jump_hint_to_index["A"] == 36
    handled = modal._handle_entry_jump_key("A")

    assert handled is True
    assert modal._get_selected_index() == 36
    modal._display_file.assert_called_with(notifications[36])
    modal.dismiss.assert_not_called()


def test_notification_jump_apostrophe_back_highlights_previous_notification() -> None:
    """Apostrophe in jump mode returns to the saved previous notification."""
    notifications = [
        _make_notification(f"n{i}", action="JumpToAgent") for i in range(3)
    ]
    modal = NotificationModal(notifications)
    modal._entry_jump_last_index = 2
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert modal._get_selected_index() == 2
    modal._display_file.assert_called_with(notifications[2])
    modal.dismiss.assert_not_called()
    assert modal._entry_jump_last_index == 0


def test_notification_jump_escape_cancels_without_dismiss() -> None:
    """Escape exits jump mode and leaves the notification modal open."""
    modal = NotificationModal([_make_notification("n1", action="JumpToAgent")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_jump_to_entry()
    handled = modal._handle_entry_jump_key("escape")

    assert handled is True
    modal.dismiss.assert_not_called()
    assert modal._entry_jump_mode_active is False
    modal._rebuild_list.assert_called_with(highlight_index=0)


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
    handled = modal._handle_entry_jump_key("q")

    assert handled is True
    assert modal._get_selected_index() == 1
    assert modal._entry_jump_mode_active is False
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
    handled = modal._handle_entry_jump_key("2")

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
    event = _KeyEvent(key="2", character="2")

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
    assert modal._handle_entry_jump_key("2") is True
    modal.dismiss.assert_not_called()

    event = MagicMock()
    event.option = option_list.get_option_at_index(option_list.highlighted)
    modal.on_option_list_option_selected(event)

    modal.dismiss.assert_called_once_with(second)


async def test_notification_jump_pilot_keeps_modal_open_and_moves_highlight() -> None:
    """Pilot coverage for the exact apostrophe-hint modal interaction."""
    inbox = _make_notification("i1", action="JumpToAgent")
    priority = _make_notification("p1", action="PlanApproval")
    dismissed: list[Notification | None] = []

    async with _TestApp().run_test() as pilot:
        modal = NotificationModal([inbox, priority], initial_index=0)
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.press("1")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert dismissed == []
        assert modal._get_selected_index() == 1
