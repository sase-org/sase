"""Tests for poll-delta, snooze expiry, and indicator refresh in toast polling."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
)
from sase.core.time import get_timezone
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

    def test_disappeared_plan_reviews_schedule_one_exact_artifact_delta(
        self,
        tmp_path: Path,
    ) -> None:
        app = _FakeApp()
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="review-agent",
            project_file="/tmp/test.sase",
            status="TALE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix="20260722090000",
            artifacts_dir=str(artifacts_dir),
        )
        app._agents = [agent]
        action_data = {
            "agent_cl_name": agent.cl_name,
            "agent_root_timestamp": agent.raw_suffix or "",
        }
        tale = _make(
            id="tale-review",
            action="PlanApproval",
            action_data=action_data,
            muted=True,
        )
        epic = _make(
            id="epic-review",
            action="EpicApproval",
            action_data=action_data,
        )
        app._notification_snapshot_cache = _snapshot([tale, epic])
        scheduled: list[tuple[tuple[Path, ...], str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((tuple(dirs), source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with (
            _patch_snapshot([]) as read_snapshot,
            patch("sase.notifications.load_notifications") as load_notifications,
        ):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == [((artifacts_dir,), "notification")]
        assert broad_refreshes == []
        assert app.notify.call_count == 0
        assert app._bell_rung == 0
        load_notifications.assert_not_called()
        assert read_snapshot.call_args.args[0] is False

    def test_unrelated_disappeared_notification_does_not_refresh(self) -> None:
        app = _FakeApp()
        unrelated = _make(id="question", action="UserQuestion")
        app._notification_snapshot_cache = _snapshot([unrelated])
        scheduled: list[tuple[object, str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((dirs, source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with _patch_snapshot([]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == []
        assert broad_refreshes == []

    def test_disappeared_plan_review_uses_broad_fallback_without_exact_agent(
        self,
    ) -> None:
        app = _FakeApp()
        review = _make(
            id="missing-agent-review",
            action="PlanApproval",
            action_data={"agent_cl_name": "not-loaded"},
        )
        app._notification_snapshot_cache = _snapshot([review])
        scheduled: list[tuple[object, str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((dirs, source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with _patch_snapshot([]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == []
        assert broad_refreshes == [("notification", True)]


class TestSnoozeExpiry:
    """Tests for snooze expiration during ``_poll_agent_completions``."""

    def test_expired_snooze_flips_to_unread_without_agent_reload(self) -> None:
        """Expiry alerts and updates counts without requesting an Agents reload."""
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
            saw_new = asyncio.run(app._poll_agent_completions())

        mock_load.assert_not_called()
        mock_expire.assert_not_called()
        assert saw_new is False
        # Row is returned unmuted by the snapshot and lands in the unread bucket.
        assert expired.muted is False
        assert expired.snooze_until is None
        assert app._indicator_tab_count(None) == 1
        assert app._indicator_tab_count(MUTED_TAB_KEY) == 0
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
            saw_new = asyncio.run(app._poll_agent_completions())

        mock_expire.assert_not_called()
        assert saw_new is False
        assert snoozed.muted is True
        assert snoozed.snooze_until == future
        assert app._indicator_tab_count(SNOOZED_TAB_KEY) == 1
        assert app._indicator_tab_count(MUTED_TAB_KEY) == 0
        assert app._indicator_tab_count(None) == 0
        assert app._bell_rung == 0
        assert app.notify.call_count == 0

    def test_expired_read_snooze_is_returned_unread_and_alerts(self) -> None:
        """Core expiry makes a snoozed-then-read row visible and unread again."""
        app = _FakeApp()
        snoozed_read = _make(
            action="JumpToAgent",
            notes=["already read but snoozed"],
            id="expired-read-snooze",
        )
        with (
            _patch_snapshot([snoozed_read], expired_ids=[snoozed_read.id]),
            patch("sase.notifications.expire_due_snoozes") as mock_expire,
        ):
            saw_new = asyncio.run(app._poll_agent_completions())

        mock_expire.assert_not_called()
        assert saw_new is False
        assert snoozed_read.muted is False
        assert snoozed_read.snooze_until is None
        assert snoozed_read.read is False
        assert app._indicator_tab_count(None) == 1
        assert app._indicator_tab_count(MUTED_TAB_KEY) == 0
        assert app.notify.call_count == 1
        assert app._bell_rung == 1

    def test_expired_plan_snooze_keeps_explicit_reminder_bell(self) -> None:
        app = _FakeApp()
        expired_plan = _make(
            action="PlanApproval",
            notes=["Plan reminder"],
            id="expired-plan-snooze",
        )

        with _patch_snapshot([expired_plan], expired_ids=[expired_plan.id]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert app.notify.call_count == 1
        assert app._bell_rung == 1

    def test_other_process_expiry_is_observed_from_persistent_unread_state(
        self,
    ) -> None:
        """Process B alerts even when process A consumed ``expired_ids``."""
        app = _FakeApp()
        previously_snoozed = _make(
            id="cross-process-expiry",
            action="JumpToAgent",
            muted=True,
            snooze_until="2099-01-01T00:00:00+00:00",
        )
        app._notification_snapshot_cache = _snapshot([previously_snoozed])
        resurfaced = _make(
            id=previously_snoozed.id,
            action="JumpToAgent",
            notes=["resurfaced elsewhere"],
        )
        resurfaced.resurfaced_at = datetime.now(get_timezone()).isoformat()

        with _patch_snapshot([resurfaced], expired_ids=[]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert app.notify.call_count == 1
        assert app._bell_rung == 1

    def test_new_resurface_generation_alerts_once_for_same_id(self) -> None:
        app = _FakeApp()
        notification_id = "same-id-reminder"
        original_timestamp = "2026-08-01T09:00:00-04:00"
        original = _make(
            id=notification_id,
            action="JumpToAgent",
            notes=["Agent completed"],
            timestamp=original_timestamp,
        )
        resurfaced = _make(
            id=notification_id,
            action="JumpToAgent",
            notes=["Agent completed"],
            timestamp=original_timestamp,
            resurfaced_at="2026-08-01T10:00:00-04:00",
        )

        with _patch_snapshot([original]):
            first_poll_saw_new = asyncio.run(app._poll_agent_completions())
        assert first_poll_saw_new is True
        assert app.notify.call_count == 1
        assert app._bell_rung == 1

        with _patch_snapshot([resurfaced], expired_ids=[notification_id]):
            resurface_poll_saw_new = asyncio.run(app._poll_agent_completions())
        assert resurface_poll_saw_new is False
        assert app.notify.call_count == 2
        assert app._bell_rung == 2

        with _patch_snapshot([resurfaced]):
            replay_poll_saw_new = asyncio.run(app._poll_agent_completions())
        assert replay_poll_saw_new is False
        assert app.notify.call_count == 2
        assert app._bell_rung == 2


class TestRingTmuxBellNonBlocking:
    """Phase 1 (sase-3q.1): the tmux bell must not block the event-loop thread."""

    def test_bell_runs_off_event_loop_thread(self) -> None:
        app = _FakeApp()
        new_notif = _make(action="UserQuestion", notes=["q?"])

        loop_thread: list[threading.Thread] = []
        bell_thread: list[threading.Thread] = []

        def _capture_bell_thread() -> None:
            bell_thread.append(threading.current_thread())

        app._ring_tmux_bell = _capture_bell_thread  # type: ignore[method-assign]

        async def _run() -> None:
            loop_thread.append(threading.current_thread())
            await app._poll_agent_completions()

        with _patch_snapshot([new_notif]):
            asyncio.run(_run())

        assert bell_thread, "bell was never invoked"
        assert bell_thread[0] is not loop_thread[0]

    def test_blocking_bell_does_not_delay_toast_or_indicator(self) -> None:
        """A bell that blocks on the worker thread must not stall the event loop."""
        app = _FakeApp()
        new_notif = _make(action="UserQuestion", notes=["q?"])

        bell_started = threading.Event()
        bell_release = threading.Event()
        notify_count_when_bell_started: list[int] = []
        indicator_when_bell_started: list[int | None] = []

        def _blocking_bell() -> None:
            notify_count_when_bell_started.append(app.notify.call_count)
            indicator_when_bell_started.append(app._indicator_count)
            bell_started.set()
            assert bell_release.wait(timeout=5.0)

        app._ring_tmux_bell = _blocking_bell  # type: ignore[method-assign]

        async def _run() -> None:
            poll_task = asyncio.create_task(app._poll_agent_completions())
            assert await asyncio.to_thread(bell_started.wait, 2.0)
            bell_release.set()
            await poll_task

        with _patch_snapshot([new_notif]):
            asyncio.run(_run())

        assert notify_count_when_bell_started == [1]
        assert indicator_when_bell_started == [1]


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
