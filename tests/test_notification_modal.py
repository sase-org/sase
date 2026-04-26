"""Tests for NotificationModal dismiss behavior."""

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
