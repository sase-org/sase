"""Tests for the tab-scoped R (read tab) notification modal action."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.confirm_dialog import ConfirmKind
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_action_types import (
    NotificationMutationResult,
)
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab
from sase.notification_gates.presentation import GATE_PANEL_ACTION_DATA_KEY

from tests._notification_modal_helpers import _make_notification


def _pushed_confirm(
    mock_app: MagicMock,
) -> tuple[ConfirmActionModal, Callable[[bool | None], None]]:
    mock_app.push_screen.assert_called_once()
    modal, callback = mock_app.push_screen.call_args.args
    assert isinstance(modal, ConfirmActionModal)
    return modal, callback


def _tracked_task(mock_app: MagicMock) -> Callable[[], Any]:
    mock_app._submit_tracked_proc.assert_called_once()
    kwargs = mock_app._submit_tracked_proc.call_args.kwargs
    assert kwargs["dedup_key"] == "notification-state"
    assert kwargs["exclusive_scopes"] == ("notification-state",)
    return mock_app._submit_tracked_proc.call_args.args[3]


def test_read_tab_prompts_before_any_dispatch_or_store_write() -> None:
    """R opens one danger confirmation before any read side effect."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal._active_notification_tag = "alpha"

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch.object(modal, "_mark_tab_read") as mock_mark,
    ):
        mock_app.screen = modal
        modal.action_read_tab()

    confirm, _callback = _pushed_confirm(mock_app)
    mock_app._submit_tracked_proc.assert_not_called()
    mock_mark.assert_not_called()
    assert confirm._kind is ConfirmKind.DANGER
    assert confirm._confirm_label == "Mark read"
    assert confirm._cancel_label == "Cancel"
    assert confirm._default == "cancel"


def test_read_tab_prompt_copy_names_tab_and_warns_about_scope() -> None:
    """The confirmation copy names the tab without presenting a page total."""
    n1 = _make_notification("n1", tags=["code-review"])
    n2 = _make_notification("n2", tags=["code-review"])
    modal = NotificationModal([n1, n2])
    modal._active_notification_tag = "code-review"

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        modal.action_read_tab()

    confirm, _callback = _pushed_confirm(mock_app)
    assert confirm._subject == "Tab: Code Review"
    assert "Every unread notification in this tab" in confirm._message
    assert "not currently loaded" in confirm._message
    assert "cannot be undone from ACE" in confirm._message
    assert "2" not in confirm._message
    assert "2" not in (confirm._subject or "")


def test_read_tab_general_prompt_uses_general_label_and_core_general_key() -> None:
    """General is displayed as General and dispatched as the core general key."""
    general = _make_notification("n1")
    tagged = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([general, tagged])
    modal._active_notification_tag = None

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        mock_app._submit_tracked_proc.return_value = object()
        modal.action_read_tab()
        confirm, callback = _pushed_confirm(mock_app)
        callback(True)

    assert confirm._subject == "Tab: General"
    task_fn = _tracked_task(mock_app)
    with patch.object(modal, "_mark_tab_read", return_value=1) as mock_mark:
        task_result = task_fn()

    mock_mark.assert_called_once_with("general")
    assert task_result.payload.ids == ("n1",)


def test_read_tab_panel_tab_prompt_and_dispatch_are_not_special_cased() -> None:
    """A declared-panel tab uses its label and dispatches its own key."""
    panel_row = _make_notification(
        "p1", action_data={GATE_PANEL_ACTION_DATA_KEY: "beads"}
    )
    other = _make_notification("o1", tags=["alpha"])
    modal = NotificationModal([panel_row, other])
    modal._active_notification_tag = "beads"

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        mock_app._submit_tracked_proc.return_value = object()
        modal.action_read_tab()
        confirm, callback = _pushed_confirm(mock_app)
        callback(True)

    assert confirm._subject == "Tab: Beads"
    task_fn = _tracked_task(mock_app)
    with patch.object(modal, "_mark_tab_read", return_value=1) as mock_mark:
        task_result = task_fn()

    mock_mark.assert_called_once_with("beads")
    assert task_result.payload.ids == ("p1",)


def test_read_tab_false_cancellation_has_no_side_effects() -> None:
    """A negative dismissal does not submit, persist, refresh, or mark local rows."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal._active_notification_tag = "alpha"

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch.object(modal, "_mark_tab_read") as mock_mark,
    ):
        mock_app.screen = modal
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        callback(False)

    assert n1.read is False
    mock_app._submit_tracked_proc.assert_not_called()
    mock_app._schedule_notification_poll.assert_not_called()
    mock_mark.assert_not_called()


def test_read_tab_none_cancellation_has_no_side_effects() -> None:
    """A None dismissal is treated as cancellation."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal._active_notification_tag = "alpha"

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch.object(modal, "_mark_tab_read") as mock_mark,
    ):
        mock_app.screen = modal
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        callback(None)

    assert n1.read is False
    mock_app._submit_tracked_proc.assert_not_called()
    mock_app._schedule_notification_poll.assert_not_called()
    mock_mark.assert_not_called()


def test_read_tab_confirmation_dispatches_captured_core_key_and_ids() -> None:
    """Confirmation uses the target frozen when R was pressed."""
    a1 = _make_notification("a1", tags=["alpha"])
    a2 = _make_notification("a2", tags=["alpha"])
    b1 = _make_notification("b1", tags=["beta"])
    modal = NotificationModal([a1, a2, b1])
    modal._active_notification_tag = "alpha"

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        mock_app._submit_tracked_proc.return_value = object()
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        modal._active_notification_tag = "beta"
        modal._notification_tab_keys = {"a1": "beta", "a2": "beta", "b1": "beta"}
        callback(True)

    task_fn = _tracked_task(mock_app)
    with patch.object(modal, "_mark_tab_read", return_value=2) as mock_mark:
        task_result = task_fn()

    mock_mark.assert_called_once_with("alpha")
    assert set(task_result.payload.ids) == {"a1", "a2"}
    assert "b1" not in task_result.payload.ids


def test_read_tab_does_not_persist_synchronously_after_confirmation() -> None:
    """Confirmation submits a tracked task instead of writing on the UI thread."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal._active_notification_tag = "alpha"

    with (
        patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app,
        patch.object(modal, "_mark_tab_read") as mock_mark,
    ):
        mock_app.screen = modal
        mock_app._submit_tracked_proc.return_value = object()
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        callback(True)

    mock_app._submit_tracked_proc.assert_called_once()
    mock_mark.assert_not_called()


def test_read_tab_confirmation_ignored_when_modal_no_longer_active() -> None:
    """A confirmed dialog cannot dispatch after its notification modal is gone."""
    n1 = _make_notification("n1", tags=["alpha"])
    modal = NotificationModal([n1])
    modal._active_notification_tag = "alpha"

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        mock_app.screen = object()
        callback(True)

    mock_app._submit_tracked_proc.assert_not_called()


def test_read_tab_no_prompt_for_missing_or_empty_target() -> None:
    """Stale tab records and empty captured row sets do not open confirmation."""
    stale = NotificationModal([_make_notification("n1", tags=["alpha"])])
    stale._active_notification_tag = "missing"
    empty = NotificationModal([_make_notification("n1", tags=["alpha"])])
    empty._active_notification_tag = "alpha"
    empty._tag_tabs = MagicMock(  # type: ignore[method-assign]
        return_value=[NotificationTagTab("alpha", "Alpha", 1)]
    )
    empty._notification_tab_keys = {}

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = stale
        stale.action_read_tab()
        mock_app.push_screen.assert_not_called()

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = empty
        empty.action_read_tab()
        mock_app.push_screen.assert_not_called()


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
