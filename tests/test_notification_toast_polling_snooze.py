"""Tests for snooze expiry during notification toast polling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
)
from sase.core.time import get_timezone

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _snapshot,
)


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
