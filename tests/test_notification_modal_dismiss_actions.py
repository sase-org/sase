"""Tests for NotificationModal dismiss and confirmation actions."""

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
    """x should require y/n confirmation for pending action notifications."""
    modal = NotificationModal([_make_notification("n1", action="PlanApproval")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    assert modal._pending_confirm_notification_id == "n1"
    assert len(modal._notifications) == 1
    modal.notify.assert_called_once_with("Dismiss pending action notification? (y/n)")


def test_dismiss_notification_requires_confirmation_for_launch_approval() -> None:
    """LaunchApproval rows use the same dismissal guard as other pending actions."""
    modal = NotificationModal([_make_notification("n1", action="LaunchApproval")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    assert modal._pending_confirm_notification_id == "n1"
    assert len(modal._notifications) == 1
    modal.notify.assert_called_once_with("Dismiss pending action notification? (y/n)")


def test_dismiss_notification_requires_confirmation_for_task_triage() -> None:
    """TaskTriage rows stay protected while their task decision is pending."""
    modal = NotificationModal([_make_notification("n1", action="TaskTriage")])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    assert modal._pending_confirm_notification_id == "n1"
    modal.notify.assert_called_once_with("Dismiss pending action notification? (y/n)")


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


def test_dismiss_last_tab_row_highlights_first_row_after_tab_fallback() -> None:
    """When the active tab disappears, dismiss highlights the new tab's first row."""
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
    oldest = _make_notification(
        "old", action="JumpToAgent", timestamp="2026-03-17T10:00:00-04:00"
    )
    newest = _make_notification(
        "new", action="JumpToAgent", timestamp="2026-03-17T13:00:00-04:00"
    )
    middle = _make_notification(
        "mid", action="JumpToAgent", timestamp="2026-03-17T12:00:00-04:00"
    )
    modal = NotificationModal([oldest, newest, middle])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_called_once_with("old")
    assert [notification.id for notification in modal._notifications] == ["new", "mid"]
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
