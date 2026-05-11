"""End-to-end checks that the TUI poll path honors the client filter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.notifications.models import Notification

from tests._notification_toasts_helpers import _FakeApp, _make


class TestTuiClientProjection:
    """End-to-end checks that the TUI poll path honors the client filter.

    These run the real ``read_notification_snapshot_for_client`` through a
    fake underlying snapshot reader, so we exercise the filter wiring, not
    just the mock.
    """

    @staticmethod
    def _agent_completion() -> Notification:
        return _make(
            sender="user-agent",
            action="JumpToAgent",
            notes=["agent done"],
            id="completion-1",
        )

    @staticmethod
    def _agent_failure() -> Notification:
        return _make(
            sender="user-agent",
            action="ViewErrorReport",
            notes=["agent failed"],
            id="failure-1",
        )

    @staticmethod
    def _plan_approval() -> Notification:
        return _make(
            action="PlanApproval",
            notes=["Plan ready for review: x.md"],
            id="plan-1",
        )

    @staticmethod
    def _user_question() -> Notification:
        return _make(
            action="UserQuestion",
            notes=["What now?"],
            id="q-1",
        )

    @staticmethod
    def _patch_raw_snapshot(notifications: list[Notification]) -> Any:
        """Patch the underlying store reader, leaving the filter wiring live."""
        from sase.notifications.filters import compute_counts

        counts = compute_counts(notifications)
        raw = SimpleNamespace(
            notifications=list(notifications),
            counts=counts.to_wire(),
            expired_ids=[],
        )

        def _reader(
            *, include_dismissed: bool = False, expire_due_snoozes: bool = False
        ) -> SimpleNamespace:
            del include_dismissed, expire_due_snoozes
            return raw

        return patch("sase.notifications.store.read_notification_snapshot", _reader)

    def test_default_tui_suppresses_agent_completion_toast_and_bell(self) -> None:
        """A successful agent_completion must not toast, ring, or seed unread ids."""
        app = _FakeApp()
        completion = self._agent_completion()
        with self._patch_raw_snapshot([completion]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 0
        assert app._bell_rung == 0
        assert app._last_unread_ids == set()
        # The counts the indicator sees come from the post-projection counts,
        # so rest/priority/muted are all zero even though the row exists in
        # the raw store.
        assert app._indicator_priority == 0
        assert app._indicator_rest == 0
        assert app._indicator_muted == 0

    def test_default_tui_keeps_agent_failure_visible(self) -> None:
        """Failed-agent rows still surface in the TUI error path."""
        app = _FakeApp()
        failure = self._agent_failure()
        with self._patch_raw_snapshot([failure]):
            asyncio.run(app._poll_agent_completions())
        # Errors should toast (severity=error) and ring the bell.
        assert app.notify.call_count == 1
        assert app._bell_rung == 1
        assert app._last_unread_ids == {failure.id}
        # Errors land in the priority bucket of the indicator (priority+errors).
        assert app._indicator_priority == 1

    def test_default_tui_keeps_plan_approval_visible(self) -> None:
        app = _FakeApp()
        plan = self._plan_approval()
        with self._patch_raw_snapshot([plan]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 1
        assert app._bell_rung == 1
        assert app._last_unread_ids == {plan.id}
        assert app._indicator_priority == 1

    def test_default_tui_keeps_user_question_visible(self) -> None:
        app = _FakeApp()
        question = self._user_question()
        with self._patch_raw_snapshot([question]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 1
        assert app._bell_rung == 1
        assert app._last_unread_ids == {question.id}
        assert app._indicator_priority == 1

    def test_mixed_batch_drops_only_completion_row(self) -> None:
        """A batch with one completion and one failure toasts only the failure."""
        app = _FakeApp()
        completion = self._agent_completion()
        failure = self._agent_failure()
        plan = self._plan_approval()
        with self._patch_raw_snapshot([completion, failure, plan]):
            asyncio.run(app._poll_agent_completions())
        # Two visible new notifications → at most two toasts (under grouping
        # threshold), one bell.
        assert app._bell_rung == 1
        assert app.notify.call_count == 2
        assert app._last_unread_ids == {failure.id, plan.id}
        # Completion's id never lands in unread tracking.
        assert completion.id not in app._last_unread_ids

    def test_refresh_notification_count_ignores_suppressed_rows(self) -> None:
        """The indicator refresh path also runs through the TUI projection."""
        app = _FakeApp()
        completion = self._agent_completion()
        plan = self._plan_approval()
        # Seed last_unread_ids with the (about-to-be-suppressed) completion so
        # we prove the refresh tears it back down.
        app._last_unread_ids = {completion.id, plan.id}
        with self._patch_raw_snapshot([completion, plan]):
            app._refresh_notification_count()
        assert app._last_unread_ids == {plan.id}
        assert app._indicator_priority == 1
        assert app._indicator_rest == 0

    def test_show_notification_modal_excludes_suppressed_completion(self) -> None:
        """Suppressed completion rows must not appear in the TUI modal source list."""
        completion = self._agent_completion()
        plan = self._plan_approval()
        failure = self._agent_failure()

        captured: dict[str, Any] = {}

        class _ModalApp(AgentNotificationMixin):
            def __init__(self) -> None:
                self._agents: list = []
                self._agent_status_overrides = {}
                self._agent_pre_question_status = {}

            def push_screen(self, screen: Any, *, callback: Any = None) -> None:  # type: ignore[override]
                del callback
                captured["modal"] = screen

        app = _ModalApp()
        with self._patch_raw_snapshot([completion, plan, failure]):
            app._show_notification_modal()

        modal = captured["modal"]
        modal_ids = {n.id for n in modal._notifications}  # type: ignore[attr-defined]
        assert completion.id not in modal_ids
        assert plan.id in modal_ids
        assert failure.id in modal_ids
