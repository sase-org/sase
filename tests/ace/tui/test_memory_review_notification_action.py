"""Tests for the memory review notification action handler."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agents._notification_handlers import handle_memory_review
from sase.notifications.models import Notification


class FakeApp:
    """Minimal AceApp stand-in for terminal action handlers."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.notifications: list[tuple[str, str]] = []
        self.suspended = False

    @contextmanager
    def suspend(self) -> Iterator[None]:
        self.events.append("suspend_enter")
        self.suspended = True
        try:
            yield
        finally:
            self.suspended = False
            self.events.append("suspend_exit")

    def notify(
        self, message: str, *, severity: str = "information", **_: object
    ) -> None:
        self.notifications.append((message, severity))


def _notification(action_data: dict[str, str]) -> Notification:
    return Notification(
        id="abc",
        timestamp="2026-05-23T12:00:00-04:00",
        sender="memory.proposed",
        action="memory_review",
        action_data=action_data,
    )


def test_handle_memory_review_runs_review_tui_under_suspend() -> None:
    app = FakeApp()
    created_with: list[str | None] = []

    class FakeMemoryReviewTuiApp:
        def __init__(self, *, initial_proposal_id: str | None = None) -> None:
            created_with.append(initial_proposal_id)

        def run(self) -> None:
            assert app.suspended is True
            app.events.append("review_run")

    with patch(
        "sase.ace.tui.actions.agents._notification_handlers.MemoryReviewTuiApp",
        FakeMemoryReviewTuiApp,
    ):
        ok = handle_memory_review(
            app,
            _notification({"proposal_id": "mem-20260523-120000-1234abcd"}),
        )

    assert ok is True
    assert created_with == ["mem-20260523-120000-1234abcd"]
    assert app.events == ["suspend_enter", "review_run", "suspend_exit"]
    assert app.notifications == []


def test_handle_memory_review_warns_when_proposal_id_missing() -> None:
    app = FakeApp()
    review_app = MagicMock()

    with patch(
        "sase.ace.tui.actions.agents._notification_handlers.MemoryReviewTuiApp",
        review_app,
    ):
        ok = handle_memory_review(app, _notification({}))

    assert ok is False
    review_app.assert_not_called()
    assert app.events == []
    assert app.notifications == [("No proposal_id in notification", "warning")]
