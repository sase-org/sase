"""Tests for NotificationModal action bindings and file path copying."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal

from tests._notification_modal_helpers import _make_notification


def test_notification_modal_binds_capital_v_to_view_image() -> None:
    assert ("V", "view_image", "View Image") in NotificationModal.BINDINGS


def test_notification_modal_binds_capital_y_to_copy_file_path() -> None:
    assert ("Y", "copy_file_path", "Copy path") in NotificationModal.BINDINGS


def test_notification_modal_binds_capital_m_to_toggle_mute() -> None:
    """Capital M is the mute toggle key; lowercase m is no longer mute."""
    assert ("M", "toggle_mute", "Toggle Mute") in NotificationModal.BINDINGS
    assert ("m", "toggle_mute", "Toggle Mute") not in NotificationModal.BINDINGS


def test_notification_modal_binds_lowercase_m_to_toggle_mark() -> None:
    """Lowercase m toggles a per-row mark."""
    assert ("m", "toggle_mark", "Mark") in NotificationModal.BINDINGS


def test_notification_modal_binds_brackets_to_tag_tabs() -> None:
    """Square brackets switch notification tag tabs."""
    assert (
        "left_square_bracket",
        "prev_notification_tag_tab",
        "Prev Tag",
    ) in NotificationModal.BINDINGS
    assert (
        "right_square_bracket",
        "next_notification_tag_tab",
        "Next Tag",
    ) in NotificationModal.BINDINGS


def test_copy_file_path_copies_current_attachment() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/tmp/first.txt", "/tmp/second.txt"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal._current_file_index = 1
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.copy_to_system_clipboard",
        return_value=True,
    ) as mock_copy:
        modal.action_copy_file_path()

    mock_copy.assert_called_once_with("/tmp/second.txt")
    modal.notify.assert_called_once_with("Copied: /tmp/second.txt")


def test_copy_file_path_shortens_home_path() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/home/example/work/file.py"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal._shorten_path = lambda path: path.replace("/home/example", "~")  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.copy_to_system_clipboard",
        return_value=True,
    ) as mock_copy:
        modal.action_copy_file_path()

    mock_copy.assert_called_once_with("~/work/file.py")
    modal.notify.assert_called_once_with("Copied: ~/work/file.py")


def test_copy_file_path_clamps_out_of_range_index() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/tmp/first.txt", "/tmp/second.txt"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal._current_file_index = 99
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.copy_to_system_clipboard",
        return_value=True,
    ) as mock_copy:
        modal.action_copy_file_path()

    assert modal._current_file_index == 0
    mock_copy.assert_called_once_with("/tmp/first.txt")


def test_copy_file_path_warns_without_highlighted_notification() -> None:
    modal = NotificationModal([])
    modal._get_highlighted_notification = lambda: None  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.copy_to_system_clipboard"
    ) as mock_copy:
        modal.action_copy_file_path()

    mock_copy.assert_not_called()
    modal.notify.assert_called_once_with("No file path to copy", severity="warning")


def test_copy_file_path_warns_without_files() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.copy_to_system_clipboard"
    ) as mock_copy:
        modal.action_copy_file_path()

    mock_copy.assert_not_called()
    modal.notify.assert_called_once_with("No file path to copy", severity="warning")


def test_copy_file_path_reports_clipboard_failure() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/tmp/first.txt"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.copy_to_system_clipboard",
        return_value=False,
    ) as mock_copy:
        modal.action_copy_file_path()

    mock_copy.assert_called_once_with("/tmp/first.txt")
    modal.notify.assert_called_once_with(
        "Failed to copy to clipboard",
        severity="error",
    )
