"""Tests for poll-delta, snooze expiry, and indicator refresh in toast polling."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

from sase.core.time import get_timezone

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
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
