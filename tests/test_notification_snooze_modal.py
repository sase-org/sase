"""Tests for SnoozeDurationModal."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from sase.ace.tui.modals.snooze_duration_modal import (
    SnoozeDurationModal,
    _tomorrow_morning,
)


def _make_modal() -> SnoozeDurationModal:
    """Return a modal with ``dismiss`` patched to capture the result."""
    modal = SnoozeDurationModal()
    modal.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    return modal


def test_preset_1_returns_15_minutes() -> None:
    modal = _make_modal()
    modal.action_preset_1()
    modal.dismiss.assert_called_once_with(timedelta(minutes=15))


def test_preset_2_returns_1_hour() -> None:
    modal = _make_modal()
    modal.action_preset_2()
    modal.dismiss.assert_called_once_with(timedelta(hours=1))


def test_preset_3_returns_4_hours() -> None:
    modal = _make_modal()
    modal.action_preset_3()
    modal.dismiss.assert_called_once_with(timedelta(hours=4))


def test_preset_4_returns__tomorrow_morning_datetime() -> None:
    modal = _make_modal()
    modal.action_preset_4()
    modal.dismiss.assert_called_once()
    (arg,), _ = modal.dismiss.call_args
    assert isinstance(arg, datetime)
    # 09:00 local on the day strictly after now's day-stamp.
    assert arg.hour == 9
    assert arg.minute == 0


def test__tomorrow_morning_anchors_to_next_day() -> None:
    """Snoozing at 22:00 on Tuesday yields Wednesday 09:00."""
    from sase.core.time import get_timezone

    tz = get_timezone()
    tuesday_evening = datetime(2026, 4, 21, 22, 0, 0, tzinfo=tz)
    target = _tomorrow_morning(now=tuesday_evening)
    assert target == datetime(2026, 4, 22, 9, 0, 0, tzinfo=tz)


def test__tomorrow_morning_skips_today_even_if_morning() -> None:
    """At 06:00 we still go to *next* day's 09:00, not 3 hours from now."""
    from sase.core.time import get_timezone

    tz = get_timezone()
    early_morning = datetime(2026, 4, 21, 6, 0, 0, tzinfo=tz)
    target = _tomorrow_morning(now=early_morning)
    assert target == datetime(2026, 4, 22, 9, 0, 0, tzinfo=tz)
