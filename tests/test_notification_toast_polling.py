"""Tests for poll-delta toasts and unread/indicator projection."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.notification_modal_tags import MUTED_TAB_KEY
from sase.notifications import notification_activity_cursor

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _plain,
    _snapshot,
)


class TestPollingDelta:
    def test_no_new_ids_no_notify(self) -> None:
        app = _FakeApp()
        existing = _make(action="PlanApproval", notes=["already-seen"])
        app._last_unread_ids = {existing.id}
        app._delivered_notification_activity_cursors = {
            notification_activity_cursor(existing)
        }
        with _patch_snapshot([existing]):
            saw_new = asyncio.run(app._poll_agent_completions())
        assert saw_new is False
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    @pytest.mark.parametrize(
        ("action", "tier_label"),
        [("PlanApproval", "Tale"), ("EpicApproval", "Epic")],
    )
    def test_single_new_plan_review_warns_and_rings(
        self, action: str, tier_label: str
    ) -> None:
        app = _FakeApp()
        new_notif = _make(
            action=action,
            notes=["Plan ready for review: sase_plan_foo.md"],
            action_data={"agent_name": "sase-n.4"},
            files=["/p/sase_plan_foo.md"],
        )
        with _patch_snapshot([new_notif]):
            saw_new = asyncio.run(app._poll_agent_completions())
        assert saw_new is True
        assert app._bell_rung == 1
        assert app._indicator_tab_count("hitl") == 1
        assert app._indicator_tab_count(None) == 0
        assert app.notify.call_count == 1
        call = app.notify.call_args
        message = call.args[0]
        severity = call.kwargs["severity"]
        assert f"{tier_label} ready for @sase-n.4" in _plain(message)
        assert severity == "warning"

    def test_already_handled_plan_approval_does_not_alert(self) -> None:
        app = _FakeApp()
        handled = _make(
            action="PlanApproval",
            notes=["Plan ready for review: handled.md"],
        )
        app._auto_dismissed_notification_ids = {handled.id}

        with _patch_snapshot([handled]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    def test_already_handled_plan_does_not_suppress_unrelated_alert(self) -> None:
        app = _FakeApp()
        handled = _make(
            action="PlanApproval",
            notes=["Plan ready for review: handled.md"],
        )
        question = _make(action="UserQuestion", notes=["Still actionable?"])
        app._auto_dismissed_notification_ids = {handled.id}

        with _patch_snapshot([handled, question]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is True
        assert app.notify.call_count == 1
        assert "Still actionable?" in app.notify.call_args.args[0]
        assert app._bell_rung == 1

    def test_two_new_mixed_emits_two_toasts(self) -> None:
        app = _FakeApp()
        a = _make(action="PlanApproval", notes=["Plan ready for review: a.md"])
        b = _make(action="UserQuestion", notes=["What?"])
        with _patch_snapshot([a, b]):
            saw_new = asyncio.run(app._poll_agent_completions())
        assert saw_new is True
        assert app.notify.call_count == 2
        assert [call.args[0] for call in app.notify.call_args_list] == [
            "Plan ready for review: a.md",
            "What?",
        ]
        assert app._bell_rung == 1

    def test_plan_and_epic_only_batch_rings_once(self) -> None:
        app = _FakeApp()
        tale = _make(action="PlanApproval", notes=["Tale ready"])
        epic = _make(action="EpicApproval", notes=["Epic ready"])

        with _patch_snapshot([tale, epic]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is True
        assert app._indicator_tab_count("hitl") == 2
        assert [call.args[0] for call in app.notify.call_args_list] == [
            "Tale ready",
            "Epic ready",
        ]
        assert app._bell_rung == 1

    def test_single_regular_notification_still_rings(self) -> None:
        app = _FakeApp()
        completed = _make(action="JumpToAgent", notes=["Agent completed"])

        with _patch_snapshot([completed]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is True
        assert app.notify.call_count == 1
        assert app._bell_rung == 1

    def test_five_new_mixed_grouped(self) -> None:
        app = _FakeApp()
        notifs = [
            _make(action="PlanApproval", notes=["Plan ready for review: a.md"]),
            _make(action="PlanApproval", notes=["Plan ready for review: b.md"]),
            _make(action="UserQuestion", notes=["q?"]),
            _make(action="ViewErrorReport", notes=["1 error"]),
            _make(
                action="JumpToChangeSpec", notes=["Sync success for x"]
            ),  # legacy notification action
        ]
        with _patch_snapshot(notifs):
            saw_new = asyncio.run(app._poll_agent_completions())
        assert saw_new is True
        # Three severity buckets → three toasts.
        assert app.notify.call_count == 3

    def test_silent_notifications_never_toast(self) -> None:
        app = _FakeApp()
        silent = _make(action="PlanApproval", notes=["silent one"], silent=True)
        with _patch_snapshot([silent]):
            saw_new = asyncio.run(app._poll_agent_completions())
        assert saw_new is False
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    def test_muted_and_read_notifications_never_alert(self) -> None:
        app = _FakeApp()
        muted = _make(action="UserQuestion", notes=["muted"], muted=True)
        read = _make(action="JumpToAgent", notes=["read"], read=True)

        with _patch_snapshot([muted, read]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert app._indicator_tab_count("hitl") == 0
        assert app._indicator_tab_count(None) == 0
        assert app._indicator_tab_count(MUTED_TAB_KEY) == 1
        assert app.notify.call_count == 0
        assert app._bell_rung == 0

    def test_seen_ids_do_not_retoast(self) -> None:
        app = _FakeApp()
        first = _make(action="UserQuestion", notes=["q1?"])
        with _patch_snapshot([first]):
            first_poll_saw_new = asyncio.run(app._poll_agent_completions())
        assert first_poll_saw_new is True
        assert app.notify.call_count == 1
        # Poll again with the same notification — no new toast.
        with _patch_snapshot([first]):
            second_poll_saw_new = asyncio.run(app._poll_agent_completions())
        assert second_poll_saw_new is False
        assert app.notify.call_count == 1

    def test_rebuilt_unread_projection_does_not_replay_generation(self) -> None:
        app = _FakeApp()
        first = _make(action="JumpToAgent", notes=["Agent completed"])

        with _patch_snapshot([first]):
            first_poll_saw_new = asyncio.run(app._poll_agent_completions())
        assert first_poll_saw_new is True
        assert app.notify.call_count == 1
        assert app._bell_rung == 1

        with _patch_snapshot([]):
            app._refresh_notification_count()
        assert app._last_unread_ids == set()

        with _patch_snapshot([first]):
            second_poll_saw_new = asyncio.run(app._poll_agent_completions())

        assert second_poll_saw_new is False
        assert app.notify.call_count == 1
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

        assert app._indicator_tab_count("hitl") == 1
        assert app._indicator_tab_count(None) == 1
        assert app._indicator_tab_count(MUTED_TAB_KEY) == 1
        assert app._last_unread_ids == {priority.id, rest.id}

    def test_single_pass_reads_the_store_exactly_once(self) -> None:
        """The count refresh must not precede a full read with a count-only one."""
        app = _FakeApp()
        notif = _make(action="JumpToAgent", notes=["done"])

        with patch(
            "sase.notifications.read_notification_snapshot",
            return_value=_snapshot([notif]),
        ) as read_snapshot:
            app._refresh_notification_count()

        assert read_snapshot.call_count == 1
        assert app._indicator_count == 1


class TestCompletionRaceOrder:
    """Section 1: the completion race converges regardless of arrival order.

    A terminal marker and its completion notification can land in either
    order. When the terminal status is already cached (loaded ahead of the
    notification), the later notification poll must still project the row
    unread. The reverse order (notification cached first, terminal status
    loaded later during finalize) is covered by
    ``tests/ace/tui/test_agent_unread_finalizer.py``.
    """

    def test_terminal_row_loaded_before_notification_becomes_unread_on_poll(
        self,
    ) -> None:
        app = _FakeApp()
        cl_name = "race-agent"
        raw_suffix = "20260722090000"
        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=cl_name,
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix=raw_suffix,
        )
        # The terminal marker already landed and the row is loaded; the
        # completion notification has not been polled yet.
        app._agents = [agent]
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": cl_name, "raw_suffix": raw_suffix},
        )

        with _patch_snapshot([completion]):
            asyncio.run(app._poll_agent_completions())

        assert agent.identity in app._unread_completed_agent_ids
