"""Tests for NotificationModal action bindings and file path copying."""

from unittest.mock import MagicMock, patch

from textual.content import Content

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_constants import (
    DEFAULT_HINT_TEXT,
    GATE_HINT_TEXT,
    QUESTION_HINT_TEXT,
)

from tests._notification_modal_helpers import _make_notification


def test_notification_modal_binds_capital_v_to_view_image() -> None:
    assert ("V", "view_image", "View") in NotificationModal.BINDINGS


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


def test_notification_modal_footer_hint_advertises_tag_tab_brackets() -> None:
    """The default footer exposes square-bracket tag navigation."""
    assert "[]: tags" in DEFAULT_HINT_TEXT
    assert "V: view" in DEFAULT_HINT_TEXT
    assert Content.from_markup(DEFAULT_HINT_TEXT).plain == DEFAULT_HINT_TEXT


def test_notification_modal_binds_g_and_capital_g_to_detail_scroll() -> None:
    """g/G jump the detail pane to the top/bottom, mirroring Ctrl+D/Ctrl+U."""
    assert ("g", "scroll_file_top", "Top") in NotificationModal.BINDINGS
    assert ("G", "scroll_file_bottom", "Bottom") in NotificationModal.BINDINGS
    assert ("shift+g", "scroll_file_bottom", "Bottom") in NotificationModal.BINDINGS


def test_notification_modal_g_scrolls_detail_pane_home() -> None:
    notification = _make_notification("n1")
    modal = NotificationModal([notification])
    scroll = MagicMock()

    def fake_query_one(selector, _type=None):
        if selector == "#notification-file-scroll":
            return scroll
        raise AssertionError(selector)

    with patch.object(modal, "query_one", fake_query_one):
        modal.action_scroll_file_top()

    scroll.scroll_home.assert_called_once_with(animate=False)


def test_notification_modal_capital_g_scrolls_detail_pane_end() -> None:
    notification = _make_notification("n1")
    modal = NotificationModal([notification])
    scroll = MagicMock()

    def fake_query_one(selector, _type=None):
        if selector == "#notification-file-scroll":
            return scroll
        raise AssertionError(selector)

    with patch.object(modal, "query_one", fake_query_one):
        modal.action_scroll_file_bottom()

    scroll.scroll_end.assert_called_once_with(animate=False)


def test_notification_modal_footer_hints_advertise_top_bottom_jump() -> None:
    """All three footer hints advertise g/G, and markup round-trips unchanged."""
    assert "g/G: top/bot" in DEFAULT_HINT_TEXT
    assert "g/G: top/bot" in QUESTION_HINT_TEXT
    assert "g/G: top/bot" in GATE_HINT_TEXT
    assert Content.from_markup(DEFAULT_HINT_TEXT).plain == DEFAULT_HINT_TEXT


def test_notification_modal_binds_capital_r_to_read_tab() -> None:
    """Capital R marks only the active tab read, not every notification."""
    assert ("R", "read_tab", "Read Tab") in NotificationModal.BINDINGS
    assert ("R", "read_all", "Read All") not in NotificationModal.BINDINGS


def test_notification_modal_footer_hint_advertises_read_tab() -> None:
    """The default footer advertises the tab-scoped read action wording."""
    assert "R: read tab" in DEFAULT_HINT_TEXT
    assert "R: read all" not in DEFAULT_HINT_TEXT


def test_copy_file_path_copies_current_attachment() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/tmp/first.txt", "/tmp/second.txt"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal._current_file_index = 1
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.schedule_copy_delivery"
    ) as schedule:
        modal.action_copy_file_path()

    schedule.assert_called_once_with(
        modal,
        "/tmp/second.txt",
        copied_label="attachment path (/tmp/second.txt)",
        task_name="sase-copy-notification-attachment-path",
    )


def test_copy_file_path_shortens_home_path() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/home/example/work/file.py"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal._shorten_path = lambda path: path.replace("/home/example", "~")  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.schedule_copy_delivery"
    ) as schedule:
        modal.action_copy_file_path()

    schedule.assert_called_once_with(
        modal,
        "~/work/file.py",
        copied_label="attachment path (~/work/file.py)",
        task_name="sase-copy-notification-attachment-path",
    )


def test_copy_file_path_clamps_out_of_range_index() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/tmp/first.txt", "/tmp/second.txt"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal._current_file_index = 99
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.schedule_copy_delivery"
    ) as schedule:
        modal.action_copy_file_path()

    assert modal._current_file_index == 0
    assert schedule.call_args.args[1] == "/tmp/first.txt"


def test_copy_file_path_warns_without_highlighted_notification() -> None:
    modal = NotificationModal([])
    modal._get_highlighted_notification = lambda: None  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.schedule_copy_delivery"
    ) as schedule:
        modal.action_copy_file_path()

    schedule.assert_not_called()
    modal.notify.assert_called_once_with("No file path to copy", severity="warning")


def test_copy_file_path_warns_without_files() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.schedule_copy_delivery"
    ) as schedule:
        modal.action_copy_file_path()

    schedule.assert_not_called()
    modal.notify.assert_called_once_with("No file path to copy", severity="warning")


def test_copy_file_path_uses_recoverable_delivery_policy() -> None:
    notification = _make_notification("n1", action="JumpToAgent")
    notification.files = ["/tmp/first.txt"]
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal_attachments.schedule_copy_delivery"
    ) as schedule:
        modal.action_copy_file_path()

    assert schedule.call_args.args[1] == "/tmp/first.txt"
    assert schedule.call_args.kwargs.get("on_failure", "modal") == "modal"
