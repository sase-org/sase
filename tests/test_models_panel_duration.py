"""Models panel duration formatting and picker tests."""

from unittest.mock import MagicMock

from sase.ace.tui.modals.models_panel import (
    _DurationPickerModal,
    _format_duration_chosen,
    _format_remaining,
)
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    OVERRIDE_UNTIL_CLEARED,
    RelativeOverrideDuration,
)


def test_format_remaining_hours_minutes() -> None:
    assert _format_remaining(3600 + 30 * 60) == "1h30m"


def test_format_remaining_seconds_when_subminute() -> None:
    assert _format_remaining(45) == "45s"


def test_format_remaining_clamps_negative() -> None:
    assert _format_remaining(-10) == "0s"


def test_format_duration_chosen_until_cleared() -> None:
    assert _format_duration_chosen(None) == "until cleared"


def test_format_duration_chosen_finite() -> None:
    assert _format_duration_chosen(90 * 60.0) == "1h30m"


def _make_duration_modal() -> _DurationPickerModal:
    modal = _DurationPickerModal()
    modal.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    return modal


def test_duration_preset_1_returns_15m() -> None:
    modal = _make_duration_modal()
    modal.action_preset_1()
    modal.dismiss.assert_called_once_with(RelativeOverrideDuration(15 * 60.0))


def test_duration_preset_3_returns_1h() -> None:
    modal = _make_duration_modal()
    modal.action_preset_3()
    modal.dismiss.assert_called_once_with(RelativeOverrideDuration(60 * 60.0))


def test_duration_preset_6_until_cleared_returns_none() -> None:
    modal = _make_duration_modal()
    modal.action_preset_6()
    modal.dismiss.assert_called_once_with(OVERRIDE_UNTIL_CLEARED)


def test_duration_t_opens_specific_time_path() -> None:
    modal = _make_duration_modal()
    modal.action_choose("t")
    modal.dismiss.assert_called_once_with(OPEN_OVERRIDE_UNTIL)
