"""Tests for per-notification toast formatting and poll delta logic."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.ace.tui.actions.agents._toasts import (
    format_batch_toasts,
    _format_notification_toast,
)
from sase.core.time import get_timezone
from sase.notifications import is_priority
from sase.notifications.filters import (
    ClientNotificationSnapshot,
    NotificationCounts,
)
from sase.notifications.models import Notification


def _make(
    *,
    sender: str = "test",
    action: str | None = None,
    notes: list[str] | None = None,
    action_data: dict[str, str] | None = None,
    files: list[str] | None = None,
    id: str | None = None,
    read: bool = False,
    silent: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
) -> Notification:
    return Notification(
        id=id or str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        silent=silent,
        muted=muted,
        snooze_until=snooze_until,
    )


class TestFormatNotificationToast:
    def test_plan_approval_with_agent_name_and_plan_file(self) -> None:
        n = _make(
            action="PlanApproval",
            notes=["Plan ready for review: sase_plan_foo.md"],
            action_data={"agent_name": "sase-n.4"},
            files=["/path/to/sase_plan_foo.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "Plan ready for @sase-n.4: sase_plan_foo.md"
        assert sev == "warning"

    def test_plan_approval_missing_agent_name_falls_back(self) -> None:
        n = _make(
            action="PlanApproval",
            notes=["Plan ready for review: sase_plan_foo.md"],
            files=["/path/to/sase_plan_foo.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "Plan ready for review: sase_plan_foo.md"
        assert sev == "warning"

    def test_plan_approval_empty_notes_uses_placeholder(self) -> None:
        n = _make(action="PlanApproval")
        msg, sev = _format_notification_toast(n)
        assert msg == "Plan ready for review"
        assert sev == "warning"

    def test_user_question_with_agent_name(self) -> None:
        n = _make(
            action="UserQuestion",
            notes=["Should I use option A or B?"],
            action_data={"agent_name": "sase-n.4"},
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "Question from @sase-n.4: Should I use option A or B?"
        assert sev == "warning"

    def test_user_question_truncates_long_notes(self) -> None:
        long = "x" * 200
        n = _make(
            action="UserQuestion",
            notes=[long],
            action_data={"agent_name": "sase-n.4"},
        )
        msg, sev = _format_notification_toast(n)
        assert len(msg) < 100
        assert sev == "warning"
        assert msg.startswith("Question from @sase-n.4:")

    def test_user_question_missing_agent(self) -> None:
        n = _make(action="UserQuestion", notes=["What color?"])
        msg, sev = _format_notification_toast(n)
        assert msg == "What color?"
        assert sev == "warning"

    def test_user_question_no_notes(self) -> None:
        n = _make(action="UserQuestion")
        msg, sev = _format_notification_toast(n)
        assert msg == "Claude is asking a question"
        assert sev == "warning"

    def test_hitl(self) -> None:
        n = _make(action="HITL", notes=["HITL waiting: step 'confirm' in deploy"])
        msg, sev = _format_notification_toast(n)
        assert msg == "HITL waiting: step 'confirm' in deploy"
        assert sev == "warning"

    def test_hitl_empty_notes(self) -> None:
        n = _make(action="HITL")
        msg, sev = _format_notification_toast(n)
        assert msg == "HITL waiting for input"
        assert sev == "warning"

    def test_view_error_report(self) -> None:
        n = _make(
            action="ViewErrorReport",
            notes=["3 error(s) in the last hour"],
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "Axe: 3 error(s) in the last hour"
        assert sev == "error"

    def test_view_error_report_no_notes(self) -> None:
        n = _make(action="ViewErrorReport")
        msg, sev = _format_notification_toast(n)
        assert msg == "Axe errors"
        assert sev == "error"

    def test_jump_to_changespec_success(self) -> None:
        n = _make(action="JumpToChangeSpec", notes=["Sync success for bar"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Sync success for bar"
        assert sev == "information"

    def test_jump_to_changespec_failure(self) -> None:
        n = _make(action="JumpToChangeSpec", notes=["Sync fail for feature/bar"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Sync fail for feature/bar"
        assert sev == "error"

    def test_jump_to_agent_success_keyword(self) -> None:
        n = _make(action="JumpToAgent", notes=["Agent finished: success"])
        _, sev = _format_notification_toast(n)
        assert sev == "information"

    def test_jump_to_agent_failure_keyword(self) -> None:
        n = _make(action="JumpToAgent", notes=["Agent failed hard"])
        _, sev = _format_notification_toast(n)
        assert sev == "error"

    def test_jump_to_agent_no_notes(self) -> None:
        n = _make(action="JumpToAgent")
        msg, sev = _format_notification_toast(n)
        assert msg == "Agent update"
        assert sev == "information"

    def test_jump_to_agent_completion_with_agent_name(self) -> None:
        n = _make(
            action="JumpToAgent",
            notes=["CLAUDE(opus) @sase-q.land completed: ace(run)-260425_161716"],
            action_data={"agent_name": "sase-q.land"},
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "CLAUDE(opus) @sase-q.land completed: ace(run)-260425_161716"
        assert sev == "information"

    def test_jump_to_agent_completion_without_agent_name(self) -> None:
        n = _make(
            action="JumpToAgent",
            notes=["CLAUDE(opus) completed: ace(run)-260425_161716"],
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "CLAUDE(opus) completed: ace(run)-260425_161716"
        assert sev == "information"

    def test_tmux(self) -> None:
        n = _make(action="Tmux", notes=["Focus pane"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Focus pane"
        assert sev == "information"

    def test_none_action(self) -> None:
        n = _make(action=None, notes=[])
        msg, sev = _format_notification_toast(n)
        assert msg == "New notification"
        assert sev == "information"

    def test_unknown_action(self) -> None:
        n = _make(action="WhoKnows", notes=["Something happened"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Something happened"
        assert sev == "information"


class TestFormatBatchToasts:
    def test_empty(self) -> None:
        assert format_batch_toasts([]) == []

    def test_single_toast_per_notification_under_threshold(self) -> None:
        notifs = [
            _make(action="PlanApproval", notes=["Plan ready for review: a.md"]),
            _make(action="UserQuestion", notes=["What?"]),
            _make(action="JumpToChangeSpec", notes=["Sync success for x"]),
        ]
        toasts = format_batch_toasts(notifs)
        assert len(toasts) == 3

    def test_groups_large_batches_by_severity(self) -> None:
        notifs = [
            _make(action="PlanApproval", notes=["Plan ready for review: a.md"]),
            _make(action="PlanApproval", notes=["Plan ready for review: b.md"]),
            _make(action="UserQuestion", notes=["What?"]),
            _make(action="ViewErrorReport", notes=["1 error"]),
            _make(action="JumpToChangeSpec", notes=["Sync success for x"]),
        ]
        toasts = format_batch_toasts(notifs)
        # One per severity bucket that has entries: error, warning, information.
        severities = [sev for _, sev in toasts]
        assert severities == ["error", "warning", "information"]
        # Warning bucket: 2 plans + 1 question = 3 warnings.
        warning_msg = next(msg for msg, sev in toasts if sev == "warning")
        assert warning_msg.startswith("3 warnings")
        assert "2 plans" in warning_msg
        assert "1 question" in warning_msg
        # Error bucket: one axe error.
        error_msg = next(msg for msg, sev in toasts if sev == "error")
        assert error_msg.startswith("1 errors")

    def test_exactly_three_emits_per_notification(self) -> None:
        notifs = [
            _make(action="PlanApproval", notes=["a"]),
            _make(action="PlanApproval", notes=["b"]),
            _make(action="PlanApproval", notes=["c"]),
        ]
        toasts = format_batch_toasts(notifs)
        assert len(toasts) == 3

    def test_four_triggers_grouping(self) -> None:
        notifs = [_make(action="PlanApproval", notes=[f"n{i}"]) for i in range(4)]
        toasts = format_batch_toasts(notifs)
        assert len(toasts) == 1
        assert toasts[0][1] == "warning"


class _FakeApp(AgentNotificationMixin):
    """Minimal scaffolding to exercise the polling delta logic."""

    def __init__(self) -> None:
        self._last_unread_ids: set[str] = set()
        self._agents: list = []
        self._agent_status_overrides = {}
        self._agent_pre_question_status = {}
        self.notify = MagicMock()  # type: ignore[assignment]
        self._bell_rung = 0
        self._indicator_priority: int | None = None
        self._indicator_rest: int | None = None
        self._indicator_count: int | None = None
        self._indicator_muted: int | None = None

    def _ring_tmux_bell(self) -> None:  # type: ignore[override]
        self._bell_rung += 1

    def _apply_notification_status_overrides(self, unread: list[Notification]) -> None:  # type: ignore[override]
        # Intentionally a no-op — status overrides aren't exercised in these tests.
        del unread

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs

        def _set_counts(priority: int, rest: int, muted: int) -> None:
            self._indicator_priority = priority
            self._indicator_rest = rest
            self._indicator_count = priority + rest
            self._indicator_muted = muted

        return SimpleNamespace(
            set_count=lambda c: setattr(self, "_indicator_count", c),
            set_counts=_set_counts,
        )


def _snapshot(
    notifications: list[Notification],
    *,
    expired_ids: list[str] | None = None,
    suppressed_types: frozenset[str] = frozenset(),
) -> ClientNotificationSnapshot:
    """Build a fake client-projected snapshot for ``AgentNotificationMixin`` tests.

    Counts are recomputed on the post-suppression visible set, matching
    what :func:`read_notification_snapshot_for_client` produces in
    production.
    """
    from sase.notifications.filters import classify_notification

    if suppressed_types:
        visible = [
            n
            for n in notifications
            if not (classify_notification(n) & suppressed_types)
        ]
    else:
        visible = list(notifications)
    priority_count = 0
    error_count = 0
    rest_count = 0
    muted_count = 0
    for notification in visible:
        if notification.read or notification.silent:
            continue
        if notification.muted:
            muted_count += 1
            continue
        from sase.notifications.priority import is_error

        if is_error(notification):
            error_count += 1
        elif is_priority(notification):
            priority_count += 1
        else:
            rest_count += 1
    counts = NotificationCounts(
        priority=priority_count,
        errors=error_count,
        rest=rest_count,
        muted=muted_count,
    )
    return ClientNotificationSnapshot(
        notifications=visible,
        counts=counts,
        expired_ids=expired_ids or [],
        raw=None,
    )


def _patch_snapshot(
    notifications: list[Notification],
    *,
    expired_ids: list[str] | None = None,
    suppressed_types: frozenset[str] = frozenset(),
) -> Any:
    return patch(
        "sase.notifications.read_notification_snapshot_for_client",
        return_value=_snapshot(
            notifications,
            expired_ids=expired_ids,
            suppressed_types=suppressed_types,
        ),
    )


class TestPollingDelta:
    def test_no_new_ids_no_notify(self) -> None:
        app = _FakeApp()
        existing = _make(action="PlanApproval", notes=["already-seen"])
        app._last_unread_ids = {existing.id}
        with _patch_snapshot([existing]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    def test_single_new_plan_approval_rings_bell_and_warns(self) -> None:
        app = _FakeApp()
        new_notif = _make(
            action="PlanApproval",
            notes=["Plan ready for review: sase_plan_foo.md"],
            action_data={"agent_name": "sase-n.4"},
            files=["/p/sase_plan_foo.md"],
        )
        with _patch_snapshot([new_notif]):
            asyncio.run(app._poll_agent_completions())
        assert app._bell_rung == 1
        assert app.notify.call_count == 1
        call = app.notify.call_args
        message = call.args[0]
        severity = call.kwargs["severity"]
        assert "Plan ready for @sase-n.4" in message
        assert severity == "warning"

    def test_two_new_mixed_emits_two_toasts(self) -> None:
        app = _FakeApp()
        a = _make(action="PlanApproval", notes=["Plan ready for review: a.md"])
        b = _make(action="UserQuestion", notes=["What?"])
        with _patch_snapshot([a, b]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 2

    def test_five_new_mixed_grouped(self) -> None:
        app = _FakeApp()
        notifs = [
            _make(action="PlanApproval", notes=["Plan ready for review: a.md"]),
            _make(action="PlanApproval", notes=["Plan ready for review: b.md"]),
            _make(action="UserQuestion", notes=["q?"]),
            _make(action="ViewErrorReport", notes=["1 error"]),
            _make(action="JumpToChangeSpec", notes=["Sync success for x"]),
        ]
        with _patch_snapshot(notifs):
            asyncio.run(app._poll_agent_completions())
        # Three severity buckets → three toasts.
        assert app.notify.call_count == 3

    def test_silent_notifications_never_toast(self) -> None:
        app = _FakeApp()
        silent = _make(action="PlanApproval", notes=["silent one"], silent=True)
        with _patch_snapshot([silent]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    def test_seen_ids_do_not_retoast(self) -> None:
        app = _FakeApp()
        first = _make(action="UserQuestion", notes=["q1?"])
        with _patch_snapshot([first]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 1
        # Poll again with the same notification — no new toast.
        with _patch_snapshot([first]):
            asyncio.run(app._poll_agent_completions())
        assert app.notify.call_count == 1


class TestSnoozeExpiry:
    """Tests for snooze expiration during ``_poll_agent_completions``."""

    def test_expired_snooze_flips_to_unread_and_rings_bell(self) -> None:
        """A snooze whose deadline passed re-enters unread + triggers the bell."""
        app = _FakeApp()
        expired = _make(
            action="JumpToAgent",
            notes=["resurfaced"],
            id="expired-snooze",
        )
        with (
            _patch_snapshot([expired], expired_ids=[expired.id]),
            patch("sase.notifications.load_notifications") as mock_load,
            patch("sase.notifications.expire_due_snoozes") as mock_expire,
        ):
            asyncio.run(app._poll_agent_completions())

        mock_load.assert_not_called()
        mock_expire.assert_not_called()
        # Row is returned unmuted by the snapshot and lands in the unread bucket.
        assert expired.muted is False
        assert expired.snooze_until is None
        assert app._indicator_rest == 1
        assert app._indicator_muted == 0
        assert app._bell_rung == 1

    def test_not_yet_due_snooze_stays_muted(self) -> None:
        """A snooze with a future deadline stays muted; no bell, no toast."""
        from datetime import timedelta

        app = _FakeApp()
        future = (datetime.now(get_timezone()) + timedelta(hours=1)).isoformat()
        snoozed = _make(
            action="JumpToAgent",
            notes=["still snoozed"],
            muted=True,
            snooze_until=future,
        )
        with (
            _patch_snapshot([snoozed]),
            patch("sase.notifications.expire_due_snoozes") as mock_expire,
        ):
            asyncio.run(app._poll_agent_completions())

        mock_expire.assert_not_called()
        assert snoozed.muted is True
        assert snoozed.snooze_until == future
        assert app._indicator_muted == 1
        assert app._indicator_rest == 0
        assert app._bell_rung == 0
        assert app.notify.call_count == 0

    def test_expired_read_snooze_rings_bell_without_unread_increase(self) -> None:
        """A snoozed-then-read row rings on expiry but does not become unread."""
        app = _FakeApp()
        snoozed_read = _make(
            action="JumpToAgent",
            notes=["already read but snoozed"],
            read=True,
            id="expired-read-snooze",
        )
        with (
            _patch_snapshot([snoozed_read], expired_ids=[snoozed_read.id]),
            patch("sase.notifications.expire_due_snoozes") as mock_expire,
        ):
            asyncio.run(app._poll_agent_completions())

        mock_expire.assert_not_called()
        # Row is no longer snoozed, but stays read — so unread bucket is empty.
        assert snoozed_read.muted is False
        assert snoozed_read.snooze_until is None
        assert snoozed_read.read is True
        assert app._indicator_rest == 0
        assert app._indicator_muted == 0
        # The reminder bell still rings — that's the whole point of the snooze.
        assert app._bell_rung == 1


class TestRefreshNotificationCount:
    def test_rebuilds_id_set_after_external_dismissal(self) -> None:
        app = _FakeApp()
        a = _make(action="UserQuestion", notes=["q?"])
        b = _make(action="PlanApproval", notes=["Plan ready for review: x.md"])
        app._last_unread_ids = {a.id, b.id}
        # After external dismissal, only `a` remains.
        with _patch_snapshot([a]):
            app._refresh_notification_count()
        assert app._last_unread_ids == {a.id}
        assert app._indicator_count == 1

    def test_counts_priority_rest_muted_and_ignored_rows(self) -> None:
        app = _FakeApp()
        priority = _make(action="PlanApproval", notes=["Plan ready"])
        rest = _make(action="JumpToAgent", notes=["done"])
        muted_priority = _make(action="UserQuestion", notes=["q?"], muted=True)
        silent_priority = _make(action="PlanApproval", notes=["silent"], silent=True)
        read_rest = _make(action="JumpToAgent", notes=["read"], read=True)

        with _patch_snapshot(
            [priority, rest, muted_priority, silent_priority, read_rest]
        ):
            app._refresh_notification_count()

        assert app._indicator_priority == 1
        assert app._indicator_rest == 1
        assert app._indicator_muted == 1
        assert app._last_unread_ids == {priority.id, rest.id}


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
