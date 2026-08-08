"""Tests for the notification modal's selected snooze-status line."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_snooze_status import (
    SNOOZE_STATUS_ID,
    NotificationSnoozeStatusMixin,
    _build_snooze_status_text,
    _format_snooze_wake_instant,
)
from tests._notification_modal_helpers import _FakeOptionList, _make_notification

NY = ZoneInfo("America/New_York")


def _notification(
    snooze_until: str | None,
    *,
    notification_id: str = "n1",
) -> Any:
    notification = _make_notification(notification_id)
    notification.snooze_until = snooze_until
    return notification


def _style_for(text: Any, fragment: str) -> str | None:
    for start, end, style in text.spans:
        if text.plain[start:end] == fragment:
            return str(style)
    return None


class TestBuildSnoozeStatusText:
    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(days=5, hours=23, minutes=59), "5d 23h"),
            (timedelta(hours=2, minutes=14), "2h 14m"),
            (timedelta(minutes=14), "14m"),
            (timedelta(seconds=30), "<1m"),
        ],
    )
    def test_future_duration_tiers(self, delta: timedelta, expected: str) -> None:
        now = datetime(2026, 3, 17, 12, 0, tzinfo=NY)
        notification = _notification((now + delta).isoformat())

        text = _build_snooze_status_text(notification, now=now)

        assert text is not None
        assert f"wakes in {expected}" in text.plain
        assert _style_for(text, expected) == "bold #D7AF5F"

    def test_no_snooze_until_hides_widget(self) -> None:
        assert _build_snooze_status_text(_notification(None)) is None

    def test_elapsed_deadline_wakes_now_with_absolute_time(self) -> None:
        now = datetime(2026, 3, 17, 12, 0, tzinfo=NY)
        notification = _notification((now - timedelta(minutes=1)).isoformat())

        text = _build_snooze_status_text(notification, now=now)

        assert text is not None
        assert text.plain == "☾ Snoozed · waking now… · today at 11:59 EDT"

    def test_malformed_deadline_degrades_without_exposing_raw_value(self) -> None:
        text = _build_snooze_status_text(
            _notification("definitely-not-a-timestamp"),
            now=datetime(2026, 3, 17, 12, 0, tzinfo=NY),
        )

        assert text is not None
        assert text.plain == "☾ Snoozed · wake time unavailable"
        assert "definitely" not in text.plain


class TestWakeInstantLabels:
    @pytest.mark.parametrize(
        ("now", "wake", "expected"),
        [
            (
                datetime(2026, 3, 17, 12, 0, tzinfo=NY),
                datetime(2026, 3, 17, 14, 5, tzinfo=NY),
                "today at 14:05 EDT",
            ),
            (
                datetime(2026, 3, 17, 12, 0, tzinfo=NY),
                datetime(2026, 3, 18, 9, 15, tzinfo=NY),
                "tomorrow at 09:15 EDT",
            ),
            (
                datetime(2026, 3, 17, 12, 0, tzinfo=NY),
                datetime(2026, 3, 20, 9, 15, tzinfo=NY),
                "Fri Mar 20 at 09:15 EDT",
            ),
            (
                datetime(2026, 12, 30, 12, 0, tzinfo=NY),
                datetime(2027, 1, 3, 9, 15, tzinfo=NY),
                "Sun Jan 3, 2027 at 09:15 EST",
            ),
            (
                datetime(2026, 10, 30, 12, 0, tzinfo=NY),
                datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC")),
                "Sun Nov 1 at 01:30 EST",
            ),
        ],
    )
    def test_absolute_wake_label_tiers(
        self, now: datetime, wake: datetime, expected: str
    ) -> None:
        assert _format_snooze_wake_instant(wake, now) == expected


class _SnoozeStatusHost(NotificationSnoozeStatusMixin):
    def __init__(self, label: Any) -> None:
        self._label = label
        self._snooze_status_timer = None

    def query_one(self, selector: str, *_args: object, **_kwargs: object) -> Any:
        if selector == f"#{SNOOZE_STATUS_ID}":
            return self._label
        raise LookupError(selector)


class TestUpdateSnoozeStatus:
    def test_none_clears_label_and_hides_it(self) -> None:
        label = MagicMock()
        host = _SnoozeStatusHost(label)

        host._update_snooze_status(None)

        label.update.assert_called_once()
        assert label.update.call_args.args[0].plain == ""
        label.add_class.assert_called_once_with("hidden")
        label.remove_class.assert_not_called()

    def test_non_snoozed_notification_clears_label_and_hides_it(self) -> None:
        label = MagicMock()
        host = _SnoozeStatusHost(label)

        host._update_snooze_status(_notification(None))

        label.update.assert_called_once()
        assert label.update.call_args.args[0].plain == ""
        label.add_class.assert_called_once_with("hidden")
        label.remove_class.assert_not_called()

    def test_snoozed_notification_sets_text_and_unhides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime(2026, 3, 17, 12, 0, tzinfo=NY)
        monkeypatch.setattr(
            "sase.ace.tui.modals.notification_modal_snooze_status._snooze_status_now",
            lambda: now,
        )
        label = MagicMock()
        host = _SnoozeStatusHost(label)

        host._update_snooze_status(
            _notification((now + timedelta(hours=2)).isoformat())
        )

        label.update.assert_called_once()
        assert "wakes in 2h" in label.update.call_args.args[0].plain
        label.remove_class.assert_called_once_with("hidden")
        label.add_class.assert_not_called()

    def test_missing_widget_degrades_silently(self) -> None:
        class _NoLabelHost(NotificationSnoozeStatusMixin):
            def query_one(self, *_args: object, **_kwargs: object) -> Any:
                raise LookupError("no such widget")

        _NoLabelHost()._update_snooze_status(_notification("not-a-timestamp"))


def _query_one_recorder(
    *,
    title: Any,
    content: Any,
    sent_at: Any,
    snooze_status: Any,
) -> Any:
    def query_one(selector: str, *_args: object, **_kwargs: object) -> Any:
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        if selector == "#notification-sent-at":
            return sent_at
        if selector == f"#{SNOOZE_STATUS_ID}":
            return snooze_status
        raise LookupError(selector)

    return query_one


class TestDisplayFileUpdatesSnoozeStatus:
    def test_selection_change_between_snoozed_and_ordinary_hides_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime(2026, 3, 17, 12, 0, tzinfo=NY)
        monkeypatch.setattr(
            "sase.ace.tui.modals.notification_modal_snooze_status._snooze_status_now",
            lambda: now,
        )
        snoozed = _notification((now + timedelta(days=1, hours=2)).isoformat())
        ordinary = _notification(None, notification_id="n2")
        modal = NotificationModal([snoozed, ordinary])
        title, content, sent_at, snooze_status = (
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        modal.query_one = MagicMock(  # type: ignore[method-assign]
            side_effect=_query_one_recorder(
                title=title,
                content=content,
                sent_at=sent_at,
                snooze_status=snooze_status,
            )
        )

        modal._display_file(snoozed)
        modal._display_file(ordinary)

        assert "wakes in 1d 2h" in snooze_status.update.call_args_list[0].args[0].plain
        snooze_status.remove_class.assert_called_once_with("hidden")
        assert snooze_status.update.call_args_list[-1].args[0].plain == ""
        snooze_status.add_class.assert_called_once_with("hidden")


class TestSnoozeStatusTimer:
    def test_start_snooze_status_timer_registers_one_interval(self) -> None:
        label = MagicMock()
        host = _SnoozeStatusHost(label)
        timer = MagicMock()
        host.set_interval = MagicMock(return_value=timer)  # type: ignore[attr-defined]

        host._start_snooze_status_timer()
        host._start_snooze_status_timer()

        host.set_interval.assert_called_once()
        assert host._snooze_status_timer is timer

    def test_timer_tick_re_resolves_current_selection_and_updates_only_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime(2026, 3, 17, 12, 0, tzinfo=NY)
        monkeypatch.setattr(
            "sase.ace.tui.modals.notification_modal_snooze_status._snooze_status_now",
            lambda: now,
        )
        first = _notification(
            (now + timedelta(hours=1)).isoformat(), notification_id="a"
        )
        second = _notification(
            (now + timedelta(hours=2, minutes=30)).isoformat(),
            notification_id="b",
        )
        modal = NotificationModal([first, second])
        option_list = _FakeOptionList(modal._create_sectioned_options())
        second_row = modal._row_for_notification_index(option_list, 1)
        option_list.highlighted = second_row
        status_label = MagicMock()

        def query_one(selector: str, *_args: object, **_kwargs: object) -> Any:
            if selector == "#notification-list":
                return option_list
            if selector == f"#{SNOOZE_STATUS_ID}":
                return status_label
            raise LookupError(selector)

        modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
        modal._display_file = MagicMock()  # type: ignore[method-assign]
        modal._rebuild_list = MagicMock()  # type: ignore[method-assign]
        modal._reset_file_scroll = MagicMock()  # type: ignore[method-assign]

        modal._refresh_snooze_status_from_timer()

        assert "wakes in 2h 30m" in status_label.update.call_args.args[0].plain
        status_label.remove_class.assert_called_once_with("hidden")
        modal._display_file.assert_not_called()
        modal._rebuild_list.assert_not_called()
        modal._reset_file_scroll.assert_not_called()

    def test_timer_tick_returns_without_touching_label_for_ordinary_row(self) -> None:
        modal = NotificationModal([_notification(None)])
        option_list = _FakeOptionList(modal._create_sectioned_options())
        option_list.highlighted = modal._row_for_notification_index(option_list, 0)
        status_label = MagicMock()

        def query_one(selector: str, *_args: object, **_kwargs: object) -> Any:
            if selector == "#notification-list":
                return option_list
            if selector == f"#{SNOOZE_STATUS_ID}":
                return status_label
            raise LookupError(selector)

        modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]

        modal._refresh_snooze_status_from_timer()

        status_label.update.assert_not_called()

    def test_unmount_stops_timer_and_keeps_pump_task_cleanup(self) -> None:
        modal = NotificationModal([])
        timer = MagicMock()
        modal._snooze_status_timer = timer

        with patch(
            "sase.ace.tui.modals.notification_modal.cancel_pump_free_tasks"
        ) as cancel:
            modal.on_unmount()

        timer.stop.assert_called_once_with()
        assert modal._snooze_status_timer is None
        cancel.assert_called_once_with(modal)
