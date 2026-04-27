"""Tests for SnoozeDurationModal."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from textual.app import App, ComposeResult
from textual.widgets import Input

from sase.ace.tui.modals.snooze_duration_modal import (
    SnoozeDurationModal,
    _tomorrow_morning,
)


class _TestApp(App[timedelta | datetime | None]):
    """Minimal app for async snooze picker tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


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


async def test_preset_1_key_dismisses_after_mount() -> None:
    """Digit shortcuts are handled by the modal, not the hidden input."""
    result: timedelta | datetime | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: timedelta | datetime | None) -> None:
            nonlocal result
            result = value

        modal = SnoozeDurationModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        custom_input = modal.query_one("#snooze-custom-input", Input)
        assert custom_input.has_class("hidden")
        assert custom_input.disabled is True

        await pilot.press("1")
        await pilot.pause()

    assert result == timedelta(minutes=15)


async def test_preset_2_key_dismisses_after_mount() -> None:
    """A second digit shortcut catches regressions beyond the first binding."""
    result: timedelta | datetime | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: timedelta | datetime | None) -> None:
            nonlocal result
            result = value

        modal = SnoozeDurationModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("2")
        await pilot.pause()

    assert result == timedelta(hours=1)


async def test_custom_key_reveals_enables_and_focuses_input() -> None:
    """``c`` is handled before the custom input becomes active."""
    async with _TestApp().run_test() as pilot:
        modal = SnoozeDurationModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        custom_input = modal.query_one("#snooze-custom-input", Input)
        assert not custom_input.has_class("hidden")
        assert custom_input.disabled is False
        assert pilot.app.focused is custom_input


async def test_escape_from_custom_hides_and_disables_input() -> None:
    """Back out of custom entry so later preset shortcuts still reach the modal."""
    result: timedelta | datetime | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: timedelta | datetime | None) -> None:
            nonlocal result
            result = value

        modal = SnoozeDurationModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        custom_input = modal.query_one("#snooze-custom-input", Input)
        custom_input.value = "30m"

        await pilot.press("escape")
        await pilot.pause()

        assert custom_input.has_class("hidden")
        assert custom_input.disabled is True
        assert custom_input.value == ""

        await pilot.press("1")
        await pilot.pause()

    assert result == timedelta(minutes=15)
