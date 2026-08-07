"""Tests for the NotificationModal tab list: order, labels, counts, and filtering.

Covers the order tabs are built in, which tab the modal opens on, and how the
active tab filters rows. Which tab *owns* a row lives in
``test_notification_modal_tab_routing``.
"""

from unittest.mock import MagicMock

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import MUTED_TAB_KEY

from tests._notification_modal_helpers import (
    _FakeOptionList,
    _make_notification,
    _option_ids,
)


def test_tag_tabs_order_counts_and_capitalized_labels() -> None:
    """Tabs are General, pinned Done, then remaining tags by display label."""
    done = _make_notification("done", action="JumpToAgent")
    # The second tag is inert: the first stored tag alone owns the row.
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
        ("review", "Review", 1),
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
        ("hitl", "Gates", 1),
        ("errors", "Errors", 1),
        (None, "General", 1),
        ("done", "Done", 1),
        ("alpha", "Alpha", 1),
        ("zeta", "Zeta", 1),
        (MUTED_TAB_KEY, "Muted", 1),
    ]


def test_declared_panels_sort_after_hitl_and_before_other_tabs() -> None:
    """Actionable panel queues precede errors, general, done, and tag tabs."""
    notifications = [
        _make_notification("hitl", action="PlanApproval"),
        _make_notification(
            "zeta-panel",
            action="CustomGate",
            action_data={"panel": "zeta-panel"},
        ),
        _make_notification(
            "beads",
            action="TaskTriage",
            action_data={"panel": "beads"},
        ),
        _make_notification("error", action="ViewErrorReport"),
        _make_notification("general", action="JumpToAgent"),
        _make_notification("done", action="JumpToAgent", tags=["done"]),
        _make_notification("memory", action="JumpToAgent", tags=["memory"]),
        _make_notification("muted", action="JumpToAgent"),
    ]
    notifications[3].sender = "axe"
    notifications[-1].muted = True

    modal = NotificationModal(notifications)

    assert [tab.tag for tab in modal._tag_tabs()] == [
        "hitl",
        "beads",
        "zeta-panel",
        "errors",
        None,
        "done",
        "memory",
        MUTED_TAB_KEY,
    ]


def test_panel_and_tag_collision_is_counted_once_and_sorted_as_panel() -> None:
    """A tag matching a declared panel shares the actionable panel tab."""
    panel = _make_notification(
        "panel",
        action="CustomGate",
        action_data={"panel": "review"},
    )
    tagged = _make_notification("tagged", action="JumpToAgent", tags=["review"])
    error = _make_notification("error", action="ViewErrorReport")
    error.sender = "axe"

    modal = NotificationModal([tagged, error, panel])

    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        ("review", 2),
        ("errors", 1),
    ]


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


def test_multi_tag_notification_is_owned_by_its_first_tag_only() -> None:
    """A two-tag row creates one tab, counted once, and dismisses one tab."""
    both = _make_notification("both", action="JumpToAgent")
    both.tags = ["done", "review"]
    untagged = _make_notification("untagged", action="JumpToAgent")

    modal = NotificationModal([both, untagged])

    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        (None, 1),
        ("done", 1),
    ]
    assert _option_ids(modal) == ["1"]

    modal._active_notification_tag = "done"
    assert _option_ids(modal) == ["0"]

    # The second tag owns nothing, so dropping the row drops exactly one tab.
    modal._active_notification_tag = "review"
    assert _option_ids(modal) == []
