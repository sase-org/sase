"""Tests for sase.ace.tui.activity_log."""

from __future__ import annotations

import time
from unittest.mock import patch

from sase.ace.tui.activity_log import ActivityEventType, ActivityLog


class TestActivityLog:
    def test_record_appends_entry(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.SESSION_START)
        assert len(log.entries) == 1
        assert log.entries[0].event == ActivityEventType.SESSION_START

    def test_record_multiple_entries(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.SESSION_START)
        log.record(ActivityEventType.ACTIVE)
        log.record(ActivityEventType.IDLE_AUTO)
        assert len(log.entries) == 3
        assert log.entries[1].event == ActivityEventType.ACTIVE
        assert log.entries[2].event == ActivityEventType.IDLE_AUTO

    def test_session_start_time_returns_none_when_empty(self) -> None:
        log = ActivityLog()
        assert log.session_start_time is None

    def test_session_start_time_returns_timestamp(self) -> None:
        log = ActivityLog()
        before = time.time()
        log.record(ActivityEventType.SESSION_START)
        after = time.time()
        ts = log.session_start_time
        assert ts is not None
        assert before <= ts <= after

    def test_session_start_time_returns_first_session_start(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.SESSION_START)
        first_ts = log.session_start_time
        log.record(ActivityEventType.ACTIVE)
        log.record(ActivityEventType.SESSION_START)
        assert log.session_start_time == first_ts

    def test_session_start_mono_returns_none_when_empty(self) -> None:
        log = ActivityLog()
        assert log.session_start_mono is None

    def test_session_start_mono_returns_monotonic(self) -> None:
        log = ActivityLog()
        before = time.monotonic()
        log.record(ActivityEventType.SESSION_START)
        after = time.monotonic()
        mono = log.session_start_mono
        assert mono is not None
        assert before <= mono <= after

    def test_compute_totals_empty(self) -> None:
        log = ActivityLog()
        active, idle, episodes = log.compute_totals()
        assert active == 0.0
        assert idle == 0.0
        assert episodes == 0

    def test_compute_totals_active_only(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.SESSION_START)
        active, idle, episodes = log.compute_totals()
        assert active > 0
        assert idle == 0.0
        assert episodes == 0

    def test_compute_totals_with_idle(self) -> None:
        log = ActivityLog()
        mono_base = 1000.0
        # Manually construct entries to control timing
        from sase.ace.tui.activity_log import _ActivityLogEntry

        log.entries = [
            _ActivityLogEntry(
                timestamp=100.0, mono=mono_base, event=ActivityEventType.SESSION_START
            ),
            _ActivityLogEntry(
                timestamp=110.0, mono=mono_base + 10, event=ActivityEventType.IDLE_AUTO
            ),
            _ActivityLogEntry(
                timestamp=120.0, mono=mono_base + 20, event=ActivityEventType.ACTIVE
            ),
        ]
        with patch("sase.ace.tui.activity_log.time") as mock_time:
            mock_time.monotonic.return_value = mono_base + 30
            active, idle, episodes = log.compute_totals()
        # SESSION_START → IDLE_AUTO: 10s active
        # IDLE_AUTO → ACTIVE: 10s idle
        # ACTIVE → now: 10s active
        assert active == 20.0
        assert idle == 10.0
        assert episodes == 1

    def test_compute_totals_multiple_idle_episodes(self) -> None:
        from sase.ace.tui.activity_log import _ActivityLogEntry

        log = ActivityLog()
        mono_base = 1000.0
        log.entries = [
            _ActivityLogEntry(
                timestamp=100.0, mono=mono_base, event=ActivityEventType.SESSION_START
            ),
            _ActivityLogEntry(
                timestamp=105.0, mono=mono_base + 5, event=ActivityEventType.IDLE_AUTO
            ),
            _ActivityLogEntry(
                timestamp=110.0, mono=mono_base + 10, event=ActivityEventType.ACTIVE
            ),
            _ActivityLogEntry(
                timestamp=115.0,
                mono=mono_base + 15,
                event=ActivityEventType.IDLE_MANUAL,
            ),
        ]
        with patch("sase.ace.tui.activity_log.time") as mock_time:
            mock_time.monotonic.return_value = mono_base + 25
            active, idle, episodes = log.compute_totals()
        assert active == 10.0  # 5s + 5s
        assert idle == 15.0  # 5s + 10s
        assert episodes == 2

    def test_current_state_empty(self) -> None:
        log = ActivityLog()
        assert log.current_state() is None

    def test_current_state_returns_last_entry(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.SESSION_START)
        log.record(ActivityEventType.ACTIVE)
        current = log.current_state()
        assert current is not None
        assert current.event == ActivityEventType.ACTIVE

    def test_is_idle_empty(self) -> None:
        log = ActivityLog()
        assert log.is_idle() is False

    def test_is_idle_when_active(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.SESSION_START)
        assert log.is_idle() is False
        log.record(ActivityEventType.ACTIVE)
        assert log.is_idle() is False

    def test_is_idle_when_idle_auto(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.IDLE_AUTO)
        assert log.is_idle() is True

    def test_is_idle_when_idle_manual(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.IDLE_MANUAL)
        assert log.is_idle() is True

    def test_is_idle_when_idle_pinned(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.IDLE_PINNED)
        assert log.is_idle() is True

    def test_is_idle_when_idle_restored(self) -> None:
        log = ActivityLog()
        log.record(ActivityEventType.IDLE_RESTORED)
        assert log.is_idle() is True


class TestActivityEventType:
    def test_all_event_types_exist(self) -> None:
        assert ActivityEventType.SESSION_START.value == "session_start"
        assert ActivityEventType.ACTIVE.value == "active"
        assert ActivityEventType.IDLE_AUTO.value == "idle_auto"
        assert ActivityEventType.IDLE_MANUAL.value == "idle_manual"
        assert ActivityEventType.IDLE_PINNED.value == "idle_pinned"
        assert ActivityEventType.IDLE_RESTORED.value == "idle_restored"
