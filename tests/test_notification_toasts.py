"""Tests for per-notification toast formatting and poll delta logic."""

from __future__ import annotations

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
from sase.notifications.models import Notification


def _make(
    *,
    action: str | None = None,
    notes: list[str] | None = None,
    action_data: dict[str, str] | None = None,
    files: list[str] | None = None,
    id: str | None = None,
    read: bool = False,
    silent: bool = False,
) -> Notification:
    return Notification(
        id=id or str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="test",
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        silent=silent,
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
        self._indicator_count: int | None = None
        self._indicator_muted: int | None = None

    def _ring_tmux_bell(self) -> None:  # type: ignore[override]
        self._bell_rung += 1

    def _apply_notification_status_overrides(self, unread: list[Notification]) -> None:  # type: ignore[override]
        # Intentionally a no-op — status overrides aren't exercised in these tests.
        del unread

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs

        def _set_counts(unread: int, muted: int) -> None:
            self._indicator_count = unread
            self._indicator_muted = muted

        return SimpleNamespace(
            set_count=lambda c: setattr(self, "_indicator_count", c),
            set_counts=_set_counts,
        )


def _patch_load(notifications: list[Notification]) -> Any:
    return patch(
        "sase.notifications.load_notifications",
        return_value=list(notifications),
    )


class TestPollingDelta:
    def test_no_new_ids_no_notify(self) -> None:
        app = _FakeApp()
        existing = _make(action="PlanApproval", notes=["already-seen"])
        app._last_unread_ids = {existing.id}
        with _patch_load([existing]):
            app._poll_agent_completions()
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
        with _patch_load([new_notif]):
            app._poll_agent_completions()
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
        with _patch_load([a, b]):
            app._poll_agent_completions()
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
        with _patch_load(notifs):
            app._poll_agent_completions()
        # Three severity buckets → three toasts.
        assert app.notify.call_count == 3

    def test_silent_notifications_never_toast(self) -> None:
        app = _FakeApp()
        silent = _make(action="PlanApproval", notes=["silent one"], silent=True)
        with _patch_load([silent]):
            app._poll_agent_completions()
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    def test_seen_ids_do_not_retoast(self) -> None:
        app = _FakeApp()
        first = _make(action="UserQuestion", notes=["q1?"])
        with _patch_load([first]):
            app._poll_agent_completions()
        assert app.notify.call_count == 1
        # Poll again with the same notification — no new toast.
        with _patch_load([first]):
            app._poll_agent_completions()
        assert app.notify.call_count == 1


class TestRefreshNotificationCount:
    def test_rebuilds_id_set_after_external_dismissal(self) -> None:
        app = _FakeApp()
        a = _make(action="UserQuestion", notes=["q?"])
        b = _make(action="PlanApproval", notes=["Plan ready for review: x.md"])
        app._last_unread_ids = {a.id, b.id}
        # After external dismissal, only `a` remains.
        with _patch_load([a]):
            app._refresh_notification_count()
        assert app._last_unread_ids == {a.id}
        assert app._indicator_count == 1
