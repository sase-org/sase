"""Tests for which NotificationModal tab owns a given notification row.

Covers the routing taxonomy: synthetic HITL and Errors tabs, declared
`panel:` queues, stored tags, and the muted/snoozed states that override them.
Tab *ordering* lives in ``test_notification_modal_tab_order``.
"""

import pytest

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
)

from tests._notification_modal_helpers import _make_notification, _option_ids


def test_hitl_actions_share_hitl_tab() -> None:
    """Plan, question, and workflow HITL rows appear in the HITL tab."""
    plan = _make_notification("plan", action="PlanApproval")
    question = _make_notification("question", action="UserQuestion")
    workflow_hitl = _make_notification("workflow", action="HITL")
    task_triage = _make_notification("task", action="TaskTriage")
    regular = _make_notification("regular", action="JumpToAgent")

    modal = NotificationModal([plan, question, workflow_hitl, task_triage, regular])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("hitl", "Gates", 4),
        (None, "General", 1),
    ]
    assert modal._active_notification_tag == "hitl"
    assert _option_ids(modal) == ["0", "1", "2", "3"]

    modal._active_notification_tag = None
    assert _option_ids(modal) == ["4"]


def test_declared_panel_routes_task_triage_out_of_hitl() -> None:
    """A declared panel takes precedence over synthetic HITL routing."""
    task_triage = _make_notification(
        "task",
        action="TaskTriage",
        action_data={"panel": " Beads "},
    )

    modal = NotificationModal([task_triage])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("beads", "Beads", 1)
    ]
    assert modal._active_notification_tag == "beads"
    assert _option_ids(modal) == ["0"]
    modal._active_notification_tag = "hitl"
    assert _option_ids(modal) == []


def test_muted_declared_panel_routes_only_to_muted() -> None:
    """Muted state takes precedence over a declared panel."""
    task_triage = _make_notification(
        "task",
        action="TaskTriage",
        action_data={"panel": "beads"},
    )
    task_triage.muted = True

    modal = NotificationModal([task_triage])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        (MUTED_TAB_KEY, "Muted", 1)
    ]


@pytest.mark.parametrize("stored_panel", ["errors", "bad panel!", "__internal", ""])
def test_invalid_stored_panel_falls_back_to_existing_routing(
    stored_panel: str,
) -> None:
    """Malformed persisted panel data never breaks or overrides HITL routing."""
    task_triage = _make_notification(
        "task",
        action="TaskTriage",
        action_data={"panel": stored_panel},
    )

    modal = NotificationModal([task_triage])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        ("hitl", "Gates", 1)
    ]


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
        ("hitl", "Gates", 1),
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


def test_snoozed_notification_appears_in_snoozed_tab_with_badge() -> None:
    """A wake time splits a muted row out of Muted and into Snoozed."""
    snoozed = _make_notification("snoozed", action="UserQuestion")
    snoozed.muted = True
    snoozed.snooze_until = "2026-03-18T09:00:00-04:00"
    muted = _make_notification("muted", action="UserQuestion")
    muted.muted = True

    modal = NotificationModal([snoozed, muted])

    assert [(tab.tag, tab.label, tab.count) for tab in modal._tag_tabs()] == [
        (SNOOZED_TAB_KEY, "Snoozed", 1),
        (MUTED_TAB_KEY, "Muted", 1),
    ]
    assert modal._active_notification_tag == SNOOZED_TAB_KEY
    assert _option_ids(modal) == ["0"]
    assert "⏰" in str(modal._create_sectioned_options()[0].prompt)

    modal._active_notification_tag = MUTED_TAB_KEY
    assert _option_ids(modal) == ["1"]


def test_snoozed_tab_carries_the_next_wake_time() -> None:
    """The Snoozed tab reports the earliest wake time it owns."""
    early = _make_notification("early", action="UserQuestion")
    early.muted = True
    early.snooze_until = "2026-03-18T09:00:00-04:00"
    late = _make_notification("late", action="UserQuestion")
    late.muted = True
    late.snooze_until = "2026-03-19T09:00:00-04:00"

    modal = NotificationModal([late, early])
    (tab,) = modal._tag_tabs()

    assert tab.tag == SNOOZED_TAB_KEY
    assert tab.kind == "snoozed"
    assert tab.next_wake_at == "2026-03-18T09:00:00-04:00"


def test_snoozed_gate_leaves_its_declared_panel_tab() -> None:
    """A snoozed `panel: beads` gate is owned by Snoozed, not by Beads."""
    snoozed = _make_notification(
        "snoozed", action="TaskTriage", action_data={"panel": "beads"}
    )
    snoozed.muted = True
    snoozed.snooze_until = "2026-03-18T09:00:00-04:00"
    awake = _make_notification(
        "awake", action="TaskTriage", action_data={"panel": "beads"}
    )

    modal = NotificationModal([snoozed, awake])

    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        ("beads", 1),
        (SNOOZED_TAB_KEY, 1),
    ]
    assert _option_ids(modal) == ["1"]
    modal._active_notification_tag = SNOOZED_TAB_KEY
    assert _option_ids(modal) == ["0"]
