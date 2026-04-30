"""Tests for NotificationModal section rendering and row selection."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal

from tests._notification_modal_helpers import _make_notification


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


def test_visual_notification_index_order_skips_section_headers() -> None:
    """Visual index order contains only selectable notification rows."""
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True
    priority = _make_notification("p1", action="PlanApproval")

    modal = NotificationModal([inbox, muted, priority])

    assert modal._visual_notification_index_order() == [2, 0, 1]


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


def test_jump_hints_render_only_on_notification_rows_in_visual_order() -> None:
    """Jump markers are assigned to selectable rows, not section headers."""
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True
    priority = _make_notification("p1", action="PlanApproval")

    modal = NotificationModal([inbox, muted, priority])
    hints = {2: "1", 0: "2", 1: "3"}
    options = modal._create_sectioned_options(jump_hints=hints)

    by_id = {str(option.id): str(option.prompt) for option in options}
    assert "[1]" not in by_id["hdr:priority"]
    assert "[2]" not in by_id["hdr:inbox"]
    assert "[3]" not in by_id["hdr:muted"]
    assert "[1]" in by_id["2"]
    assert "[2]" in by_id["0"]
    assert "[3]" in by_id["1"]
