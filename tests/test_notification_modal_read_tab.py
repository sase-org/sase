"""Tests for the tab-scoped R (read tab) notification modal action."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_action_types import (
    NotificationMutationResult,
)
from sase.notification_gates.presentation import GATE_PANEL_ACTION_DATA_KEY

from tests._notification_modal_helpers import _make_notification


def test_read_tab_dispatches_captured_core_key_and_ignores_other_tab() -> None:
    """R persists only the active tab's core key and captures only its rows."""
    a1 = _make_notification("a1", tags=["alpha"])
    a2 = _make_notification("a2", tags=["alpha"])
    b1 = _make_notification("b1", tags=["beta"])
    modal = NotificationModal([a1, a2, b1])
    modal._active_notification_tag = "alpha"

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app._submit_tracked_task.return_value = object()
        modal.action_read_tab()

    mock_app._submit_tracked_task.assert_called_once()
    kwargs = mock_app._submit_tracked_task.call_args.kwargs
    assert kwargs["dedup_key"] == "notification-state"
    assert kwargs["exclusive_scopes"] == ("notification-state",)
    task_fn = mock_app._submit_tracked_task.call_args.args[3]

    with patch.object(modal, "_mark_tab_read", return_value=2) as mock_mark:
        task_result = task_fn()

    mock_mark.assert_called_once_with("alpha")
    assert set(task_result.payload.ids) == {"a1", "a2"}
    assert "b1" not in task_result.payload.ids


def test_read_tab_general_tab_converts_none_to_core_general_key() -> None:
    """The General tab (tag ``None``) dispatches the core ``general`` key."""
    general = _make_notification("n1")
    tagged = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([general, tagged])
    modal._active_notification_tag = None

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app._submit_tracked_task.return_value = object()
        modal.action_read_tab()

    task_fn = mock_app._submit_tracked_task.call_args.args[3]
    with patch.object(modal, "_mark_tab_read", return_value=1) as mock_mark:
        task_result = task_fn()

    mock_mark.assert_called_once_with("general")
    assert task_result.payload.ids == ("n1",)


def test_read_tab_panel_tab_is_not_special_cased() -> None:
    """A declared-panel tab dispatches its own key, same as a plain tag tab."""
    panel_row = _make_notification(
        "p1", action_data={GATE_PANEL_ACTION_DATA_KEY: "beads"}
    )
    other = _make_notification("o1", tags=["alpha"])
    modal = NotificationModal([panel_row, other])
    modal._active_notification_tag = "beads"

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app._submit_tracked_task.return_value = object()
        modal.action_read_tab()

    task_fn = mock_app._submit_tracked_task.call_args.args[3]
    with patch.object(modal, "_mark_tab_read", return_value=1) as mock_mark:
        task_result = task_fn()

    mock_mark.assert_called_once_with("beads")
    assert task_result.payload.ids == ("p1",)


def test_read_tab_does_not_persist_synchronously() -> None:
    """Dispatch submits a tracked task instead of writing on the UI thread."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal._active_notification_tag = "alpha"

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch.object(modal, "_mark_tab_read") as mock_mark,
    ):
        mock_app._submit_tracked_task.return_value = object()
        modal.action_read_tab()

    mock_mark.assert_not_called()


def test_complete_read_tab_error_leaves_read_flags_unchanged_and_notifies() -> None:
    """A failed write reports an error and never flips local read flags."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal.notify = MagicMock()  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=("n1",), success=False, message="disk busy"
        )
        modal._complete_read_tab(result)

    assert n1.read is False
    modal.notify.assert_called_once_with(
        "Could not mark tab read: disk busy", severity="error"
    )
    modal._rebuild_list.assert_not_called()


def test_complete_read_tab_success_marks_only_captured_ids_and_refreshes() -> None:
    """A successful write marks only the captured ids and rebuilds the list."""
    n1 = _make_notification("n1", tags=["alpha"])
    n2 = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([n1, n2])
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=("n1",), success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    assert n1.read is True
    assert n2.read is False
    mock_app._schedule_notification_poll.assert_called_once_with(source="mutation")
    modal._rebuild_list.assert_called_once()


def test_complete_read_tab_after_tab_switch_keeps_new_tab_and_leaves_it_unread() -> (
    None
):
    """Switching tabs before completion neither reverts the tab nor reads it."""
    a1 = _make_notification("a1", tags=["alpha"])
    b1 = _make_notification("b1", tags=["beta"])
    modal = NotificationModal([a1, b1])
    captured_ids = ("a1",)
    # Simulate the user navigating to another tab while persistence is in flight.
    modal._active_notification_tag = "beta"
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=captured_ids, success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    assert a1.read is True
    assert b1.read is False
    assert modal._active_notification_tag == "beta"
