"""Tests for NotificationModal row marking and tag tab actions."""

from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.widgets import notification_tab_style

from tests._notification_modal_helpers import _make_notification


@pytest.fixture(autouse=True)
def _shipped_notification_tab_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Beads' shipped lowered priority stable under broad xdist runs."""
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": {"notification_tabs": {"beads": {"priority": 0}}}},
    )


def test_toggle_mark_adds_id_to_marked_set() -> None:
    """m adds the highlighted id to the marked set and advances the cursor."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([n1, n2])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    modal.action_toggle_mark()

    assert "n1" in modal._marked_notification_ids
    modal._rebuild_list.assert_called_once_with(highlight_index=1)


def test_toggle_mark_removes_id_when_already_marked() -> None:
    """m on an already-marked row toggles it off."""
    n1 = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([n1])
    modal._marked_notification_ids = {"n1"}
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    modal.action_toggle_mark()

    assert "n1" not in modal._marked_notification_ids


def test_marked_row_label_has_marker_prefix() -> None:
    """Marked rows render the '▶ ' marker before the regular prefix."""
    notification = _make_notification("n1", action="JumpToAgent")
    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification, is_marked=True)
    assert label.plain.startswith("▶ ")


def test_x_with_marks_bulk_dismisses_all_marked() -> None:
    """When marks exist, x bulk-dismisses every marked row in one persistence call."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    n3 = _make_notification("n3", action="JumpToAgent")
    modal = NotificationModal([n1, n2, n3])
    modal._marked_notification_ids = {"n1", "n3"}
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal.mark_many_dismissed"
    ) as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_called_once_with(["n1", "n3"])
    assert [n.id for n in modal._notifications] == ["n2"]
    assert modal._marked_notification_ids == set()
    modal._rebuild_list.assert_called_once()


def test_x_with_marks_including_plan_question_requires_confirmation() -> None:
    """Bulk dismiss with a plan/question marked needs a single y/n confirm."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="PlanApproval")
    modal = NotificationModal([n1, n2])
    modal._marked_notification_ids = {"n1", "n2"}
    modal.notify = MagicMock()  # type: ignore[method-assign]

    with patch(
        "sase.ace.tui.modals.notification_modal.mark_many_dismissed"
    ) as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_not_called()
    assert modal._pending_confirm_notification_ids == ["n1", "n2"]
    assert len(modal._notifications) == 2
    modal.notify.assert_called_once()

    with patch(
        "sase.ace.tui.modals.notification_modal.mark_many_dismissed"
    ) as mock_mark:
        modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
        modal.action_confirm_dismiss_notification()

    mock_mark.assert_called_once_with(["n1", "n2"])
    assert modal._notifications == []
    assert modal._marked_notification_ids == set()
    assert modal._pending_confirm_notification_ids is None


def test_x_without_marks_unchanged_behavior() -> None:
    """No marks → x dismisses only the highlighted row (legacy path)."""
    n1 = _make_notification("n1", action="JumpToAgent")
    n2 = _make_notification("n2", action="JumpToAgent")
    modal = NotificationModal([n1, n2])
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_called_once_with("n1")
    assert [n.id for n in modal._notifications] == ["n2"]


def test_cancel_clears_bulk_pending() -> None:
    """Cancel clears pending bulk dismiss and toasts a single message."""
    modal = NotificationModal(
        [
            _make_notification("n1", action="PlanApproval"),
            _make_notification("n2", action="JumpToAgent"),
        ]
    )
    modal._pending_confirm_notification_ids = ["n1", "n2"]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal.action_cancel_dismiss_notification()

    assert modal._pending_confirm_notification_ids is None
    modal.notify.assert_called_once_with("Dismiss canceled")


def test_switching_tag_tabs_clears_marks_and_pending_confirms() -> None:
    """Tab switches clear modal-local state that could affect hidden rows."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    modal._marked_notification_ids = {"done"}
    modal._pending_confirm_notification_id = "done"
    modal._pending_confirm_notification_ids = ["done"]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    modal._switch_notification_tag_tab("review")

    assert modal._active_notification_tag == "review"
    assert modal._marked_notification_ids == set()
    assert modal._pending_confirm_notification_id is None
    assert modal._pending_confirm_notification_ids is None
    modal._rebuild_list.assert_called_once_with(highlight_index=1)


def test_next_prev_tag_tab_cycles_without_general_tab() -> None:
    """Bracket actions cycle through the computed tab order without General."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    assert [tab.tag for tab in modal._tag_tabs()] == ["done", "review"]
    assert modal._active_notification_tag == "done"

    modal.action_next_notification_tag_tab()
    assert modal._active_notification_tag == "review"

    modal.action_next_notification_tag_tab()
    assert modal._active_notification_tag == "done"

    modal.action_prev_notification_tag_tab()
    assert modal._active_notification_tag == "review"


def test_panel_and_hyphenated_tag_labels_are_humanized() -> None:
    """Panel and tag tabs share title-style labels split on separators."""
    beads = _make_notification(
        "beads",
        action="TaskTriage",
        action_data={"panel": "beads"},
    )
    code_review = _make_notification(
        "review",
        action="JumpToAgent",
        tags=["code-review"],
    )

    modal = NotificationModal([beads, code_review])

    assert [(tab.tag, tab.label) for tab in modal._tag_tabs()] == [
        ("code-review", "Code Review"),
        ("beads", "Beads"),
    ]


def test_dismiss_last_row_in_active_tag_falls_back_to_nearest_tab() -> None:
    """When a tag disappears after dismiss, the active tab moves to its neighbor."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    modal._active_notification_tag = "done"
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    modal._rebuild_list = MagicMock()  # type: ignore[method-assign]

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed") as mock_mark:
        modal.action_dismiss_notification()

    mock_mark.assert_called_once_with("done")
    assert modal._active_notification_tag == "review"
