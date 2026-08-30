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
from sase.ops.names import NOTIFY_APPLY_STATE
from sase.notification_gates.presentation import GATE_PANEL_ACTION_DATA_KEY

from tests._notification_modal_helpers import _make_notification, _wire_fake_option_list


def _pushed_confirm(
    mock_app: MagicMock,
) -> tuple[ConfirmActionModal, Callable[[bool | None], None]]:
    mock_app.push_screen.assert_called_once()
    modal, callback = mock_app.push_screen.call_args.args
    assert isinstance(modal, ConfirmActionModal)
    return modal, callback


def _durable_submission(
    mock_app: MagicMock,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    mock_app._submit_durable_proc.assert_called_once()
    args = mock_app._submit_durable_proc.call_args.args
    kwargs = mock_app._submit_durable_proc.call_args.kwargs
    assert kwargs["operation"] == NOTIFY_APPLY_STATE
    assert kwargs["concurrency_keys"] == ("notification-state",)
    return args, kwargs


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
    mock_app._submit_durable_proc.assert_not_called()
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
        mock_app._submit_durable_proc.return_value = object()
        modal.action_read_tab()
        confirm, callback = _pushed_confirm(mock_app)
        callback(True)

    assert confirm._subject == "Tab: General"
    args, kwargs = _durable_submission(mock_app)
    assert args == (["sase", "notify", "apply-state-many", "read"],)
    request = kwargs["request"]
    assert request["tab_key"] == "general"
    assert request["ids"] == ["n1"]


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
        mock_app._submit_durable_proc.return_value = object()
        modal.action_read_tab()
        confirm, callback = _pushed_confirm(mock_app)
        callback(True)

    assert confirm._subject == "Tab: Beads"
    args, kwargs = _durable_submission(mock_app)
    assert args == (["sase", "notify", "apply-state-many", "read"],)
    request = kwargs["request"]
    assert request["tab_key"] == "beads"
    assert request["ids"] == ["p1"]


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
    mock_app._submit_durable_proc.assert_not_called()
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
    mock_app._submit_durable_proc.assert_not_called()
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
        mock_app._submit_durable_proc.return_value = object()
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        modal._active_notification_tag = "beta"
        modal._notification_tab_keys = {"a1": "beta", "a2": "beta", "b1": "beta"}
        callback(True)

    args, kwargs = _durable_submission(mock_app)
    assert args == (["sase", "notify", "apply-state-many", "read"],)
    request = kwargs["request"]
    assert request["tab_key"] == "alpha"
    assert set(request["ids"]) == {"a1", "a2"}
    assert "b1" not in request["ids"]


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
        mock_app._submit_durable_proc.return_value = object()
        modal.action_read_tab()
        _confirm, callback = _pushed_confirm(mock_app)
        callback(True)

    mock_app._submit_durable_proc.assert_called_once()
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

    mock_app._submit_durable_proc.assert_not_called()


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
    assert modal._notifications == [n1]
    modal.notify.assert_called_once_with(
        "Could not mark tab read: disk busy", severity="error"
    )
    modal._rebuild_list.assert_not_called()


def test_complete_read_tab_success_drops_acted_rows_and_refreshes() -> None:
    """A successful write drops acted rows and rebuilds the list."""
    n1 = _make_notification("n1", tags=["alpha"])
    n2 = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([n1, n2])
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=("n1",), success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    assert n1.read is True
    assert n1 not in modal._notifications
    assert modal._notifications == [n2]
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
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=captured_ids, success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    assert a1.read is True
    assert a1 not in modal._notifications
    assert modal._notifications == [b1]
    assert b1.read is False
    assert modal._active_notification_tag == "beta"


def test_complete_read_tab_emptied_tab_moves_to_neighbor() -> None:
    """Reading the last row of a tab drops it and selects a surviving neighbor."""
    a1 = _make_notification("a1", tags=["alpha"])
    b1 = _make_notification("b1", tags=["beta"])
    modal = NotificationModal([a1, b1])
    modal._active_notification_tag = "alpha"
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=("a1",), success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    assert modal._notifications == [b1]
    assert modal._active_notification_tag == "beta"
    assert "alpha" not in [tab.tag for tab in modal._tag_tabs()]


def test_complete_read_tab_last_tab_empties_the_modal() -> None:
    """Reading the last remaining tab leaves an empty unread list."""
    a1 = _make_notification("a1", tags=["alpha"])
    modal = NotificationModal([a1])
    modal._active_notification_tag = "alpha"
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=("a1",), success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    assert modal._notifications == []
    assert modal._active_notification_tag is None
    assert modal._tag_tabs() == []


def test_complete_read_tab_rebuilds_option_list_without_acted_rows() -> None:
    """The visible option list drops acted rows instead of keeping a read marker."""
    a1 = _make_notification("a1", tags=["alpha"])
    a2 = _make_notification("a2", tags=["alpha"])
    b1 = _make_notification("b1", tags=["beta"])
    modal = NotificationModal([a1, a2, b1])
    modal._active_notification_tag = "alpha"
    option_list = _wire_fake_option_list(modal)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read", ids=("a1",), success=True, message="Tab marked read"
        )
        modal._complete_read_tab(result)

    visible_ids = [
        modal._notifications[int(option.id)].id
        for option in option_list.options
        if not option.disabled and option.id is not None
    ]
    assert "a1" not in visible_ids
    assert visible_ids == ["a2"]
    assert modal._active_notification_tag == "alpha"


def test_complete_read_tab_forgets_marks_and_pending_confirmations() -> None:
    """Marks and pending dismiss confirmations do not survive removed rows."""
    a1 = _make_notification("a1", tags=["alpha"])
    a2 = _make_notification("a2", tags=["alpha"])
    modal = NotificationModal([a1, a2])
    modal._active_notification_tag = "alpha"
    modal._marked_notification_ids = {"a1", "a2"}
    modal._pending_confirm_notification_id = "a1"
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read",
            ids=("a1", "a2"),
            success=True,
            message="Tab marked read",
        )
        modal._complete_read_tab(result)

    assert modal._marked_notification_ids == set()
    assert modal._pending_confirm_notification_id is None


def test_complete_read_tab_toast_reports_store_count() -> None:
    """The toast uses the store-side matched count, including the singular form."""
    n1 = _make_notification("n1", tags=["alpha"])
    leftover = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([n1, leftover])
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read",
            ids=("n1",),
            success=True,
            message="Tab marked read",
            matched_count=5,
        )
        modal._complete_read_tab(result)

    modal.notify.assert_called_once_with("Marked 5 notifications read")

    n1 = _make_notification("n1", tags=["alpha"])
    leftover = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([n1, leftover])
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read",
            ids=("n1",),
            success=True,
            message="Tab marked read",
            matched_count=1,
        )
        modal._complete_read_tab(result)

    modal.notify.assert_called_once_with("Marked 1 notification read")

    leftover = _make_notification("n2", tags=["alpha"])
    modal = NotificationModal([leftover])
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch.object(NotificationModal, "app", new_callable=MagicMock) as mock_app:
        mock_app.screen = modal
        result = NotificationMutationResult(
            action="read",
            ids=("missing",),
            success=True,
            message="Tab marked read",
            matched_count=0,
        )
        modal._complete_read_tab(result)

    modal.notify.assert_not_called()
