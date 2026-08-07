"""Tests for single-valued notification tab ownership.

Tab ownership is decided once, in the Rust core. These tests pin the
user-visible consequences of that rule and keep the two entry points into it —
the modal adapter and the notification snapshot — from drifting apart.
"""

from pathlib import Path

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
    classify_notification_modal_tabs,
    notification_matches_tag_tab,
)
from sase.core.notification_store_facade import (
    read_notifications_snapshot,
    rewrite_notifications,
)
from sase.notifications import Notification

from tests.notification_store.helpers import make_notification


def _snoozed(notification: Notification, until: str) -> Notification:
    notification.muted = True
    notification.snooze_until = until
    return notification


def _fixture_rows() -> list[Notification]:
    """A row for every branch of the tab-ownership precedence."""
    error = make_notification(id="error", action="ViewErrorReport")
    error.sender = "axe"
    muted = make_notification(id="muted", action="JumpToAgent")
    muted.muted = True
    return [
        make_notification(id="hitl", action="PlanApproval"),
        make_notification(
            id="beads", action="TaskTriage", action_data={"panel": "beads"}
        ),
        error,
        make_notification(id="general", action="JumpToAgent"),
        make_notification(id="tagged", action="JumpToAgent", tags=["alpha", "beta"]),
        make_notification(id="done", action="JumpToAgent", tags=["done"]),
        muted,
        _snoozed(
            make_notification(id="snoozed", action="UserQuestion"),
            "2099-01-01T09:00:00-05:00",
        ),
    ]


def test_a_two_tag_row_owns_exactly_one_tab() -> None:
    """The regression: one row, one tab, counted once."""
    row = make_notification(id="x", tags=["alpha", "beta"])

    tabs, row_tab_keys = classify_notification_modal_tabs([row])

    assert [(tab.tag, tab.count) for tab in tabs] == [("alpha", 1)]
    assert row_tab_keys == {"x": "alpha"}
    assert notification_matches_tag_tab(row, "alpha")
    assert not notification_matches_tag_tab(row, "beta")


def test_a_wake_time_splits_snoozed_out_of_muted() -> None:
    """Muted with a wake time is Snoozed; muted without one is Muted."""
    snoozed = _snoozed(make_notification(id="s"), "2099-01-01T09:00:00-05:00")
    muted = make_notification(id="m")
    muted.muted = True

    tabs, _ = classify_notification_modal_tabs([snoozed, muted])

    assert [(tab.tag, tab.count) for tab in tabs] == [
        (SNOOZED_TAB_KEY, 1),
        (MUTED_TAB_KEY, 1),
    ]
    assert notification_matches_tag_tab(snoozed, SNOOZED_TAB_KEY)
    assert notification_matches_tag_tab(muted, MUTED_TAB_KEY)


def test_a_snoozed_gate_leaves_its_declared_panel_tab() -> None:
    """A sleeping `panel: beads` gate is absent from Beads until it wakes."""
    snoozed = _snoozed(
        make_notification(id="s", action="TaskTriage", action_data={"panel": "beads"}),
        "2099-01-01T09:00:00-05:00",
    )

    tabs, _ = classify_notification_modal_tabs([snoozed])

    assert [tab.tag for tab in tabs] == [SNOOZED_TAB_KEY]


def test_every_row_lands_in_exactly_one_of_the_built_tabs() -> None:
    """Tab counts sum to the row count, so no row is double-counted."""
    rows = _fixture_rows()

    tabs, row_tab_keys = classify_notification_modal_tabs(rows)

    assert sum(tab.count for tab in tabs) == len(rows)
    assert set(row_tab_keys) == {row.id for row in rows}
    assert {tab.tag for tab in tabs} == set(row_tab_keys.values())


def test_the_pure_tab_key_agrees_with_the_core_classification() -> None:
    """The single-row helper never disagrees with the batch core call."""
    rows = _fixture_rows()

    _, row_tab_keys = classify_notification_modal_tabs(rows)

    for row in rows:
        assert notification_matches_tag_tab(row, row_tab_keys[row.id])


def test_modal_tabs_match_the_snapshot_tabs(tmp_path: Path) -> None:
    """The adapter and the snapshot cannot drift for a shared fixture."""
    rows = _fixture_rows()
    path = tmp_path / "notifications.jsonl"
    rewrite_notifications(str(path), rows)

    snapshot = read_notifications_snapshot(path)
    modal_tabs, _ = classify_notification_modal_tabs(list(snapshot.notifications))

    assert [(tab.key, tab.count) for tab in snapshot.tabs] == [
        ("general" if tab.tag is None else tab.tag, tab.count) for tab in modal_tabs
    ]
    assert [tab.kind for tab in snapshot.tabs] == [tab.kind for tab in modal_tabs]


def test_snapshot_tab_counts_agree_with_the_legacy_counters(tmp_path: Path) -> None:
    """Per-tab counts partition exactly the rows the counters describe."""
    rows = _fixture_rows()
    path = tmp_path / "notifications.jsonl"
    rewrite_notifications(str(path), rows)

    snapshot = read_notifications_snapshot(path)
    counts = snapshot.counts

    assert sum(tab.count for tab in snapshot.tabs) == (
        counts.priority + counts.errors + counts.rest + counts.muted
    )
