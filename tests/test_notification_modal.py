"""Tests for NotificationModal dismiss behavior."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

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
    """A snoozed row's label appends a '· in {time}' badge."""
    from datetime import datetime as _datetime
    from datetime import timedelta as _timedelta

    from sase.core.time import get_timezone

    notification = _make_notification("n1", action="JumpToAgent")
    notification.muted = True
    deadline = _datetime.now(get_timezone()) + _timedelta(minutes=14)
    notification.snooze_until = deadline.isoformat()

    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)
    assert "· in" in label.plain


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
