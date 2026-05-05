"""Tests for NotificationModal actions, labels, dismiss, mute, and snooze behavior."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal

from tests._notification_modal_helpers import _make_notification


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


def test_bulk_dismiss_persists_once_removes_rows_and_rebuilds_once() -> None:
    """Bulk dismiss persists one ID burst and rebuilds the modal once."""
    modal = NotificationModal(
        [
            _make_notification("n1", action="JumpToAgent"),
            _make_notification("n2", action="JumpToAgent"),
            _make_notification("n3", action="JumpToAgent"),
        ]
    )
    modal._get_selected_index = lambda: 1  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal.mark_many_dismissed"
    ) as mock_mark:
        dismissed = modal._bulk_dismiss_notifications_by_index(2)

    assert dismissed == 2
    mock_mark.assert_called_once_with(["n2", "n3"])
    assert [notification.id for notification in modal._notifications] == ["n1"]
    modal._rebuild_list.assert_called_once_with(highlight_index=0)


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


def test_agent_completion_label_omits_redundant_sender_and_action_badge() -> None:
    """Agent completion rows spend width on the result, not duplicate labels."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.sender = "user-agent"
    notification.notes = ["CODEX(gpt-5.5) @sase-1l.1 completed: ace(run)-260430_175319"]
    notification.files = ["/tmp/chat.md", "/tmp/diff.diff"]
    modal = NotificationModal([notification])

    label = modal._create_styled_label(notification)

    assert "[user-agent]" not in label.plain
    assert "[agent]" not in label.plain
    assert "2 files" in label.plain


def test_error_label_keeps_sender_and_error_badge() -> None:
    """Error rows keep their source and action badge because both add context."""
    notification = _make_notification("n1", action="ViewErrorReport")
    notification.sender = "user-agent"
    notification.notes = ["Agent failed"]
    modal = NotificationModal([notification])

    label = modal._create_styled_label(notification)

    assert "[user-agent]" in label.plain
    assert "[error]" in label.plain


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
