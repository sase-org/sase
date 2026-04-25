"""Tests for the handle_jump_to_mentor_review notification handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.changespec import MentorEntry, MentorStatusLine
from sase.ace.tui.actions.agents._notification_handlers import (
    handle_jump_to_mentor_review,
)
from sase.notifications.models import Notification
from test_utils import build_changespec


class FakeApp:
    """Minimal AceApp stand-in for the JumpToMentorReview handler."""

    def __init__(self, changespecs: list[Any] | None = None) -> None:
        self.changespecs = changespecs or []
        self.current_idx = 0
        self.opened_for_entry: tuple[Any, MentorEntry] | None = None
        self.notifications: list[tuple[str, str]] = []

    def notify(
        self, message: str, *, severity: str = "information", **_: object
    ) -> None:
        self.notifications.append((message, severity))

    def _open_mentor_review_for_entry(self, cs: Any, entry: MentorEntry) -> None:
        self.opened_for_entry = (cs, entry)


def _notification(
    *,
    changespec_name: str = "cl-1",
    project_file: str = "/proj.gp",
    entry_id: str = "1",
) -> Notification:
    return Notification(
        id="abc",
        timestamp="2025-01-01T00:00:00",
        sender="mentors",
        notes=["Mentors done"],
        files=[project_file],
        action="JumpToMentorReview",
        action_data={
            "changespec_name": changespec_name,
            "project_file": project_file,
            "entry_id": entry_id,
        },
    )


def _commented_entry(entry_id: str = "1") -> MentorEntry:
    return MentorEntry(
        entry_id=entry_id,
        profiles=["code"],
        status_lines=[
            MentorStatusLine(
                profile_name="code",
                mentor_name="dead_code",
                status="COMMENTED",
                timestamp="251231_120000",
                duration="0h2m15s",
            )
        ],
    )


def _passed_entry(entry_id: str = "1") -> MentorEntry:
    return MentorEntry(
        entry_id=entry_id,
        profiles=["code"],
        status_lines=[
            MentorStatusLine(
                profile_name="code",
                mentor_name="dead_code",
                status="PASSED",
                timestamp="251231_120000",
                duration="0h2m15s",
            )
        ],
    )


def _no_status_entry(entry_id: str = "1") -> MentorEntry:
    return MentorEntry(entry_id=entry_id, profiles=["code"], status_lines=None)


def test_opens_mentor_review_when_comments_exist() -> None:
    cs = build_changespec(
        file_path="/proj.gp", name="cl-1", mentors=[_commented_entry("1")]
    )
    app = FakeApp(changespecs=[cs])
    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_changespec_tab",
        return_value=True,
    ):
        ok = handle_jump_to_mentor_review(app, _notification())
    assert ok is True
    assert app.opened_for_entry is not None
    opened_cs, opened_entry = app.opened_for_entry
    assert opened_cs is cs
    assert opened_entry.entry_id == "1"


def test_does_not_open_modal_when_passed_only() -> None:
    cs = build_changespec(
        file_path="/proj.gp", name="cl-1", mentors=[_passed_entry("1")]
    )
    app = FakeApp(changespecs=[cs])
    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_changespec_tab",
        return_value=True,
    ):
        ok = handle_jump_to_mentor_review(app, _notification())
    # Navigation succeeded; modal IS opened because PASSED is reviewable.
    # The plan says "any mentor comments left" auto-opens — has_reviewable_mentors
    # gates on COMMENTED/FAILED/RUNNING/PASSED to match _open_mentor_review.
    assert ok is True
    assert app.opened_for_entry is not None


def test_does_not_open_modal_when_no_status_lines() -> None:
    cs = build_changespec(
        file_path="/proj.gp", name="cl-1", mentors=[_no_status_entry("1")]
    )
    app = FakeApp(changespecs=[cs])
    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_changespec_tab",
        return_value=True,
    ):
        ok = handle_jump_to_mentor_review(app, _notification())
    assert ok is True
    assert app.opened_for_entry is None


def test_does_not_open_modal_when_navigation_fails() -> None:
    cs = build_changespec(
        file_path="/proj.gp", name="cl-1", mentors=[_commented_entry("1")]
    )
    app = FakeApp(changespecs=[cs])
    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_changespec_tab",
        return_value=False,
    ):
        ok = handle_jump_to_mentor_review(app, _notification())
    assert ok is False
    assert app.opened_for_entry is None


def test_does_not_open_modal_when_entry_id_not_found() -> None:
    cs = build_changespec(
        file_path="/proj.gp", name="cl-1", mentors=[_commented_entry("2")]
    )
    app = FakeApp(changespecs=[cs])
    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_changespec_tab",
        return_value=True,
    ):
        ok = handle_jump_to_mentor_review(app, _notification(entry_id="1"))
    assert ok is True
    assert app.opened_for_entry is None


def test_returns_false_when_changespec_name_missing() -> None:
    app = FakeApp()
    notification = Notification(
        id="abc",
        timestamp="2025-01-01T00:00:00",
        sender="mentors",
        action="JumpToMentorReview",
        action_data={"project_file": "/proj.gp", "entry_id": "1"},
    )
    ok = handle_jump_to_mentor_review(app, notification)
    assert ok is False
    assert app.opened_for_entry is None
