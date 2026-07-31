"""Tests for NotificationModal tab rendering and row selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    NotificationTagStrip,
)

from tests._notification_modal_helpers import _FakeOptionList, _make_notification


def _option_ids(modal: NotificationModal) -> list[str | None]:
    return [option.id for option in modal._create_sectioned_options()]


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


def test_compat_sectioned_options_wrapper_matches_flat_options() -> None:
    """The old option-builder entrypoint delegates to the flat renderer."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])

    assert _option_ids(modal) == [
        option.id for option in modal._create_notification_options()
    ]


def test_hitl_actions_share_hitl_tab() -> None:
    """Plan, question, and workflow HITL rows appear in the HITL tab."""
    plan = _make_notification("plan", action="PlanApproval")
    question = _make_notification("question", action="UserQuestion")
    workflow_hitl = _make_notification("workflow", action="HITL")
    task_triage = _make_notification("task", action="TaskTriage")
    regular = _make_notification("regular", action="JumpToAgent")

    modal = NotificationModal([plan, question, workflow_hitl, task_triage, regular])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("hitl", "HITL", 4),
        (None, "General", 1),
    ]
    assert modal._active_notification_tag == "hitl"
    assert _option_ids(modal) == ["0", "1", "2", "3"]

    modal._active_notification_tag = None
    assert _option_ids(modal) == ["4"]


def test_error_notifications_share_errors_tab() -> None:
    """Axe and failed-agent error rows appear in the Errors tab."""
    axe_error = _make_notification("axe", action="ViewErrorReport")
    axe_error.sender = "axe"
    agent_error = _make_notification("agent", action="ViewErrorReport")
    agent_error.sender = "user-agent"
    non_error_view = _make_notification("other", action="ViewErrorReport")
    non_error_view.sender = "test"

    modal = NotificationModal([axe_error, agent_error, non_error_view])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("errors", "Errors", 2),
        (None, "General", 1),
    ]
    assert modal._active_notification_tag == "errors"
    assert _option_ids(modal) == ["0", "1"]

    modal._active_notification_tag = None
    assert _option_ids(modal) == ["2"]


def test_synthetic_tabs_take_precedence_over_stored_tags() -> None:
    """HITL and Errors rows do not also populate regular tag tabs."""
    plan = _make_notification("plan", action="PlanApproval")
    plan.tags = ["done"]
    error = _make_notification("error", action="ViewErrorReport")
    error.sender = "axe"
    error.tags = ["review"]
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]

    modal = NotificationModal([plan, error, done])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("hitl", "HITL", 1),
        ("errors", "Errors", 1),
        ("done", "Done", 1),
    ]

    modal._active_notification_tag = "done"
    assert _option_ids(modal) == ["2"]


def test_muted_hitl_notification_appears_only_in_muted_tab() -> None:
    """Muted HITL rows are isolated in the Muted tab."""
    notification = _make_notification("plan", action="PlanApproval")
    notification.muted = True

    modal = NotificationModal([notification])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        (MUTED_TAB_KEY, "Muted", 1)
    ]
    assert modal._active_notification_tag == MUTED_TAB_KEY
    assert _option_ids(modal) == ["0"]

    modal._active_notification_tag = "hitl"
    assert _option_ids(modal) == []


def test_muted_error_notification_appears_only_in_muted_tab() -> None:
    """Muted error rows do not populate Errors."""
    muted_error = _make_notification("muted-error", action="ViewErrorReport")
    muted_error.sender = "axe"
    muted_error.muted = True
    active_error = _make_notification("active-error", action="ViewErrorReport")
    active_error.sender = "axe"

    modal = NotificationModal([muted_error, active_error])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("errors", "Errors", 1),
        (MUTED_TAB_KEY, "Muted", 1),
    ]
    assert _option_ids(modal) == ["1"]

    modal._active_notification_tag = MUTED_TAB_KEY
    assert _option_ids(modal) == ["0"]


def test_muted_tagged_notification_appears_only_in_muted_tab() -> None:
    """Muted tagged rows do not populate stored tag tabs or General."""
    muted_tagged = _make_notification("muted-tagged", action="JumpToAgent")
    muted_tagged.tags = ["done", "review"]
    muted_tagged.muted = True
    active_done = _make_notification("active-done", action="JumpToAgent")
    active_done.tags = ["done"]
    untagged = _make_notification("untagged", action="JumpToAgent")

    modal = NotificationModal([muted_tagged, active_done, untagged])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        (None, "General", 1),
        ("done", "Done", 1),
        (MUTED_TAB_KEY, "Muted", 1),
    ]
    assert _option_ids(modal) == ["2"]

    modal._active_notification_tag = "done"
    assert _option_ids(modal) == ["1"]
    modal._active_notification_tag = "review"
    assert _option_ids(modal) == []
    modal._active_notification_tag = MUTED_TAB_KEY
    assert _option_ids(modal) == ["0"]


def test_snoozed_notification_appears_in_muted_tab_with_badge() -> None:
    """Snoozed rows are muted rows and keep their snooze badge."""
    notification = _make_notification("snoozed", action="UserQuestion")
    notification.muted = True
    notification.snooze_until = "2026-03-18T09:00:00-04:00"

    modal = NotificationModal([notification])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        (MUTED_TAB_KEY, "Muted", 1)
    ]
    assert _option_ids(modal) == ["0"]
    assert "⏰" in str(modal._create_sectioned_options()[0].prompt)


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


def test_tag_tabs_order_counts_and_capitalized_labels() -> None:
    """Tabs are General, pinned Done, then remaining tags by display label."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done", "review"]
    foobar = _make_notification("foobar", action="JumpToAgent")
    foobar.tags = ["foobar"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    untagged = _make_notification("untagged", action="JumpToAgent")

    modal = NotificationModal([done, foobar, review, untagged])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        (None, "General", 1),
        ("done", "Done", 1),
        ("foobar", "Foobar", 1),
        ("review", "Review", 2),
    ]


def test_mixed_tab_order_places_muted_last() -> None:
    """Muted is the final synthetic tab after active tabs and stored tags."""
    hitl = _make_notification("hitl", action="PlanApproval")
    error = _make_notification("error", action="ViewErrorReport")
    error.sender = "axe"
    general = _make_notification("general", action="JumpToAgent")
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    zeta = _make_notification("zeta", action="JumpToAgent")
    zeta.tags = ["zeta"]
    alpha = _make_notification("alpha", action="JumpToAgent")
    alpha.tags = ["alpha"]
    muted = _make_notification("muted", action="JumpToAgent")
    muted.muted = True

    modal = NotificationModal([zeta, muted, done, hitl, alpha, error, general])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("hitl", "HITL", 1),
        ("errors", "Errors", 1),
        (None, "General", 1),
        ("done", "Done", 1),
        ("alpha", "Alpha", 1),
        ("zeta", "Zeta", 1),
        (MUTED_TAB_KEY, "Muted", 1),
    ]


def test_literal_muted_tag_does_not_collide_with_synthetic_muted_tab() -> None:
    """A stored 'muted' tag remains distinct from muted-state taxonomy."""
    tagged_muted = _make_notification("tagged-muted", action="JumpToAgent")
    tagged_muted.tags = ["muted"]
    muted = _make_notification("actually-muted", action="JumpToAgent")
    muted.muted = True

    modal = NotificationModal([tagged_muted, muted])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("muted", "Muted", 1),
        (MUTED_TAB_KEY, "Muted", 1),
    ]
    assert _option_ids(modal) == ["0"]

    modal._active_notification_tag = MUTED_TAB_KEY
    assert _option_ids(modal) == ["1"]


def test_all_tagged_notifications_open_on_first_tag_tab() -> None:
    """When there is no General tab, the modal starts on the first tag tab."""
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]

    modal = NotificationModal([review, done])

    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        ("done", 1),
        ("review", 1),
    ]
    assert modal._active_notification_tag == "done"
    assert _option_ids(modal) == ["1"]


def test_on_mount_highlights_first_visible_row_when_initial_is_hidden() -> None:
    """Initial mount falls forward to a visible row in the starting tag tab."""
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    modal = NotificationModal([review, done], initial_index=0)
    option_list = _FakeOptionList(modal._create_sectioned_options())
    option_list.focus = MagicMock()  # type: ignore[method-assign]

    def query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#notification-list":
            return option_list
        raise LookupError(selector)

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    modal._display_file = MagicMock()  # type: ignore[method-assign]

    modal.on_mount()

    assert option_list.highlighted == 0
    modal._display_file.assert_called_once_with(done)


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

    assert _option_ids(modal) == ["0", "2"]
    assert modal._visual_notification_index_order() == [0, 2]


def test_general_tab_excludes_tagged_notifications() -> None:
    """Untagged rows stay in General and tagged rows stay out of it."""
    untagged = _make_notification("untagged", action="JumpToAgent")
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    modal = NotificationModal([untagged, done])

    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        (None, 1),
        ("done", 1),
    ]
    assert _option_ids(modal) == ["0"]

    modal._active_notification_tag = "done"
    assert _option_ids(modal) == ["1"]


def test_multi_tag_notification_appears_in_each_tag_tab_not_general() -> None:
    """Multi-tag rows render in every matching tag tab, never in General."""
    both = _make_notification("both", action="JumpToAgent")
    both.tags = ["done", "review"]
    untagged = _make_notification("untagged", action="JumpToAgent")

    modal = NotificationModal([both, untagged])

    assert _option_ids(modal) == ["1"]

    modal._active_notification_tag = "done"
    assert _option_ids(modal) == ["0"]

    modal._active_notification_tag = "review"
    assert _option_ids(modal) == ["0"]


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
