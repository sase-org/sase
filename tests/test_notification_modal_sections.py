"""Tests for NotificationModal row rendering, ordering, and row selection.

Covers the flat option list a tab renders: sort order, jump hints, row labels,
and the guards that run when no row is selected. Tab taxonomy lives in
``test_notification_modal_tab_routing`` and ``test_notification_modal_tab_order``.
"""

from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import MUTED_TAB_KEY

from tests._notification_modal_helpers import _make_notification, _option_ids


def test_active_tab_renders_flat_newest_first_without_section_rows() -> None:
    """Rows in the active tab are flat and sorted by descending timestamp."""
    older = _make_notification(
        "i1", action="JumpToAgent", timestamp="2026-03-17T10:00:00-04:00"
    )
    muted_middle = _make_notification(
        "m1", action="JumpToAgent", timestamp="2026-03-17T12:00:00-04:00"
    )
    muted_middle.muted = True
    newest = _make_notification(
        "i2", action="JumpToAgent", timestamp="2026-03-17T13:00:00-04:00"
    )
    muted_newest = _make_notification(
        "m2", action="JumpToAgent", timestamp="2026-03-17T14:00:00-04:00"
    )
    muted_newest.muted = True

    modal = NotificationModal([older, muted_middle, newest, muted_newest])
    options = modal._create_sectioned_options()

    assert [option.id for option in options] == ["2", "0"]
    assert all(not option.disabled for option in options)
    assert all(not str(option.id).startswith("hdr:") for option in options)

    modal._active_notification_tag = MUTED_TAB_KEY
    assert _option_ids(modal) == ["3", "1"]


def test_resurfaced_row_sorts_as_recent_activity() -> None:
    """A resurfaced snooze leads the tab despite its old creation time."""
    resurfaced = _make_notification(
        "old", action="JumpToAgent", timestamp="2026-03-10T09:00:00-04:00"
    )
    resurfaced.resurfaced_at = "2026-03-17T15:00:00-04:00"
    newer = _make_notification(
        "new", action="JumpToAgent", timestamp="2026-03-17T13:00:00-04:00"
    )

    modal = NotificationModal([resurfaced, newer])

    assert _option_ids(modal) == ["0", "1"]
    # The immutable original sent time is untouched by the reordering.
    assert modal._notifications[0].timestamp == "2026-03-10T09:00:00-04:00"


def test_compat_sectioned_options_wrapper_matches_flat_options() -> None:
    """The old option-builder entrypoint delegates to the flat renderer."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])

    assert _option_ids(modal) == [
        option.id for option in modal._create_notification_options()
    ]


def test_visual_notification_index_order_matches_flat_render() -> None:
    """Visual index order contains selectable notification rows only."""
    older = _make_notification(
        "i1", action="JumpToAgent", timestamp="2026-03-17T10:00:00-04:00"
    )
    newest = _make_notification(
        "i2", action="JumpToAgent", timestamp="2026-03-17T13:00:00-04:00"
    )
    middle = _make_notification(
        "i3", action="JumpToAgent", timestamp="2026-03-17T12:00:00-04:00"
    )

    modal = NotificationModal([older, newest, middle])

    assert modal._visual_notification_index_order() == [1, 2, 0]


def test_malformed_timestamp_does_not_crash_and_sinks() -> None:
    """A non-parseable timestamp sinks to the bottom without raising."""
    good_old = _make_notification(
        "i1", action="JumpToAgent", timestamp="2026-03-17T10:00:00-04:00"
    )
    bad = _make_notification("i2", action="JumpToAgent", timestamp="not-a-timestamp")
    good_new = _make_notification(
        "i3", action="JumpToAgent", timestamp="2026-03-17T13:00:00-04:00"
    )

    modal = NotificationModal([good_old, bad, good_new])

    assert _option_ids(modal) == ["2", "0", "1"]


def test_equal_timestamps_preserve_insertion_order() -> None:
    """Byte-equal timestamps keep their original relative order."""
    first = _make_notification(
        "i1", action="JumpToAgent", timestamp="2026-03-17T12:00:00-04:00"
    )
    second = _make_notification(
        "i2", action="JumpToAgent", timestamp="2026-03-17T12:00:00-04:00"
    )
    third = _make_notification(
        "i3", action="JumpToAgent", timestamp="2026-03-17T12:00:00-04:00"
    )

    modal = NotificationModal([first, second, third])

    assert _option_ids(modal) == ["0", "1", "2"]


def test_jump_hints_render_on_notification_rows_in_visual_order() -> None:
    """Jump markers are assigned to selectable rows in flat visual order."""
    first = _make_notification("i1", action="JumpToAgent")
    second = _make_notification("i2", action="JumpToAgent")
    third = _make_notification("i3", action="JumpToAgent")

    modal = NotificationModal([first, second, third])
    hints = {0: "1", 1: "2", 2: "3"}
    options = modal._create_sectioned_options(jump_hints=hints)

    by_id = {str(option.id): str(option.prompt) for option in options}
    assert all(not option.disabled for option in options)
    assert "[1]" in by_id["0"]
    assert "[2]" in by_id["1"]
    assert "[3]" in by_id["2"]


def test_styled_label_includes_compact_tag_badges() -> None:
    """Row labels show bounded tag badges without letting long tags dominate."""
    notification = _make_notification("n1", action="JumpToAgent")
    notification.tags = [
        "done",
        "really-long-tag-name",
        "review",
        "extra",
    ]

    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)

    assert "#done" in label.plain
    assert "#really-long..." in label.plain
    assert "+1" in label.plain


def test_get_selected_index_returns_none_for_legacy_header_like_option() -> None:
    """_get_selected_index remains defensive if given a non-row option id."""
    modal = NotificationModal([_make_notification("i1", action="JumpToAgent")])

    fake_option = MagicMock()
    fake_option.id = "hdr:inbox"
    fake_list = MagicMock()
    fake_list.highlighted = 0
    fake_list.get_option_at_index.return_value = fake_option
    modal.query_one = MagicMock(return_value=fake_list)  # type: ignore[method-assign]

    assert modal._get_selected_index() is None


def test_dismiss_no_ops_when_no_notification_is_selected() -> None:
    """Action dismiss is a no-op when _get_selected_index returns None."""
    modal = NotificationModal([_make_notification("i1", action="JumpToAgent")])
    modal._get_selected_index = lambda: None  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    modal._rebuild_list.assert_not_called()
    assert len(modal._notifications) == 1


def test_toggle_mute_no_ops_when_no_notification_is_selected() -> None:
    """Action toggle_mute is a no-op when _get_selected_index returns None."""
    modal = NotificationModal([_make_notification("i1", action="JumpToAgent")])
    modal._get_selected_index = lambda: None  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_muted") as mock_mark:
        modal.action_toggle_mute()

    mock_mark.assert_not_called()
    modal._rebuild_list.assert_not_called()
