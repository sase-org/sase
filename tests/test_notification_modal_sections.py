"""Tests for NotificationModal section rendering and row selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import NotificationTagStrip

from tests._notification_modal_helpers import _make_notification


def test_sections_render_in_priority_errors_inbox_muted_order() -> None:
    """Options appear in PRIORITY → ERRORS → INBOX → MUTED order with gap spacers."""
    priority = _make_notification("p1", action="PlanApproval")
    error = _make_notification("e1", action="ViewErrorReport")
    error.sender = "axe"
    inbox = _make_notification("i1", action="JumpToAgent")
    muted = _make_notification("m1", action="JumpToAgent")
    muted.muted = True

    modal = NotificationModal([priority, error, inbox, muted])
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert ids == [
        "hdr:priority",
        "0",
        "hdr:gap:errors",
        "hdr:errors",
        "1",
        "hdr:gap:inbox",
        "hdr:inbox",
        "2",
        "hdr:gap:muted",
        "hdr:muted",
        "3",
    ]


def test_no_gap_before_first_or_after_last_section() -> None:
    """Spacer rows only appear between adjacent populated sections."""
    inbox = _make_notification("i1", action="JumpToAgent")
    modal = NotificationModal([inbox])
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert ids == ["hdr:inbox", "0"]


def test_axe_error_lives_in_errors_section() -> None:
    """An axe ViewErrorReport notification renders under ERRORS, not PRIORITY."""
    n = _make_notification("e1", action="ViewErrorReport")
    n.sender = "axe"
    modal = NotificationModal([n])
    assert modal._section_for(n) == "errors"


def test_user_agent_error_lives_in_errors_section() -> None:
    """A failed-agent ViewErrorReport notification renders under ERRORS."""
    n = _make_notification("e1", action="ViewErrorReport")
    n.sender = "user-agent"
    modal = NotificationModal([n])
    assert modal._section_for(n) == "errors"


def test_muted_error_falls_back_to_muted() -> None:
    """A muted error still goes to MUTED; mute precedence wins."""
    n = _make_notification("e1", action="ViewErrorReport")
    n.sender = "axe"
    n.muted = True
    modal = NotificationModal([n])
    assert modal._section_for(n) == "muted"


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


def test_inbox_group_sorted_newest_first() -> None:
    """Inbox entries render in descending-timestamp order within their section."""
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
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert ids == ["hdr:inbox", "1", "2", "0"]


def test_each_group_sorts_independently() -> None:
    """Each section is sorted newest-first; section order is unchanged."""
    p_old = _make_notification(
        "p1", action="PlanApproval", timestamp="2026-03-17T08:00:00-04:00"
    )
    p_new = _make_notification(
        "p2", action="PlanApproval", timestamp="2026-03-17T14:00:00-04:00"
    )
    e_old = _make_notification(
        "e1", action="ViewErrorReport", timestamp="2026-03-17T09:00:00-04:00"
    )
    e_old.sender = "axe"
    e_new = _make_notification(
        "e2", action="ViewErrorReport", timestamp="2026-03-17T15:00:00-04:00"
    )
    e_new.sender = "axe"
    i_old = _make_notification(
        "i1", action="JumpToAgent", timestamp="2026-03-17T07:00:00-04:00"
    )
    i_new = _make_notification(
        "i2", action="JumpToAgent", timestamp="2026-03-17T16:00:00-04:00"
    )
    m_old = _make_notification(
        "m1", action="JumpToAgent", timestamp="2026-03-17T06:00:00-04:00"
    )
    m_old.muted = True
    m_new = _make_notification(
        "m2", action="JumpToAgent", timestamp="2026-03-17T17:00:00-04:00"
    )
    m_new.muted = True

    modal = NotificationModal([p_old, e_old, i_old, m_old, p_new, e_new, i_new, m_new])
    options = modal._create_sectioned_options()
    ids = [opt.id for opt in options]

    assert ids == [
        "hdr:priority",
        "4",
        "0",
        "hdr:gap:errors",
        "hdr:errors",
        "5",
        "1",
        "hdr:gap:inbox",
        "hdr:inbox",
        "6",
        "2",
        "hdr:gap:muted",
        "hdr:muted",
        "7",
        "3",
    ]


def test_jump_visual_order_matches_sorted_render() -> None:
    """_visual_notification_index_order returns indexes in the new sorted order."""
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
    """A non-parseable timestamp sinks to the bottom of its group without raising."""
    good_old = _make_notification(
        "i1", action="JumpToAgent", timestamp="2026-03-17T10:00:00-04:00"
    )
    bad = _make_notification("i2", action="JumpToAgent", timestamp="not-a-timestamp")
    good_new = _make_notification(
        "i3", action="JumpToAgent", timestamp="2026-03-17T13:00:00-04:00"
    )

    modal = NotificationModal([good_old, bad, good_new])
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert ids == ["hdr:inbox", "2", "0", "1"]


def test_equal_timestamps_preserve_insertion_order() -> None:
    """Byte-equal timestamps keep their original relative order (stable sort)."""
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
    options = modal._create_sectioned_options()

    ids = [opt.id for opt in options]
    assert ids == ["hdr:inbox", "0", "1", "2"]


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


def test_tag_tabs_order_counts_and_pin_done() -> None:
    """Tag tabs are All, pinned done, then remaining tags alphabetically."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done", "review"]
    foobar = _make_notification("foobar", action="JumpToAgent")
    foobar.tags = ["foobar"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    untagged = _make_notification("untagged", action="JumpToAgent")

    modal = NotificationModal([done, foobar, review, untagged])

    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        (None, 4),
        ("done", 1),
        ("foobar", 1),
        ("review", 2),
    ]


def test_active_tag_filters_rows_but_preserves_original_option_ids() -> None:
    """Tag tabs filter display rows without renumbering option ids."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    both = _make_notification("both", action="JumpToAgent")
    both.tags = ["done", "review"]
    untagged = _make_notification("untagged", action="JumpToAgent")

    modal = NotificationModal([done, review, both, untagged])
    modal._active_notification_tag = "done"
    options = modal._create_sectioned_options()

    assert [opt.id for opt in options] == ["hdr:inbox", "0", "2"]
    assert modal._visual_notification_index_order() == [0, 2]


def test_untagged_notifications_only_render_in_all_tab() -> None:
    """Untagged rows stay in All and do not appear in a tag tab."""
    untagged = _make_notification("untagged", action="JumpToAgent")
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    modal = NotificationModal([untagged, done])

    assert [opt.id for opt in modal._create_sectioned_options()] == [
        "hdr:inbox",
        "0",
        "1",
    ]

    modal._active_notification_tag = "done"
    assert [opt.id for opt in modal._create_sectioned_options()] == [
        "hdr:inbox",
        "1",
    ]


def test_active_tag_section_headers_count_visible_rows_only() -> None:
    """Section headers/counts are recomputed after tag filtering."""
    priority = _make_notification("priority", action="PlanApproval")
    priority.tags = ["done"]
    error = _make_notification("error", action="ViewErrorReport")
    error.sender = "axe"
    error.tags = ["review"]
    inbox = _make_notification("inbox", action="JumpToAgent")
    inbox.tags = ["done"]

    modal = NotificationModal([priority, error, inbox])
    modal._active_notification_tag = "done"
    options = modal._create_sectioned_options()

    assert [opt.id for opt in options] == [
        "hdr:priority",
        "0",
        "hdr:gap:inbox",
        "hdr:inbox",
        "2",
    ]
    by_id = {str(option.id): str(option.prompt) for option in options}
    assert "· 1" in by_id["hdr:priority"]
    assert "· 1" in by_id["hdr:inbox"]


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


def test_tag_strip_click_posts_selected_tag() -> None:
    """The tag strip keeps stable click ranges for tag tabs."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    strip = NotificationTagStrip(modal._tag_tabs(), None)
    strip.post_message = MagicMock()  # type: ignore[method-assign]

    start, _end = strip._tab_ranges["done"]
    strip.on_click(SimpleNamespace(x=start))

    message = strip.post_message.call_args.args[0]
    assert isinstance(message, NotificationTagStrip.TabClicked)
    assert message.tag == "done"
