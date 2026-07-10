"""Absolute-time parsing and modal behavior for Models-panel overrides."""

from __future__ import annotations

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
    ResolvedOverrideUntil,
    _resolve_override_until,
)

_EASTERN = ZoneInfo("America/New_York")


def _clock(value: datetime):
    def now(_timezone: tzinfo) -> datetime:
        return value

    return now


def _resolve(value: str, now: datetime) -> ResolvedOverrideUntil:
    return _resolve_override_until(value, timezone=_EASTERN, clock=_clock(now))


@pytest.mark.parametrize(
    ("raw", "hour", "minute"),
    [
        ("5pm", 17, 0),
        ("5:30 PM", 17, 30),
        ("17:30", 17, 30),
        ("1730", 17, 30),
        ("0500", 5, 0),
    ],
)
def test_clock_forms_resolve_later_today(raw: str, hour: int, minute: int) -> None:
    result = _resolve(raw, datetime(2026, 7, 10, 4, 0, tzinfo=_EASTERN))

    assert result.target == datetime(2026, 7, 10, hour, minute, tzinfo=_EASTERN)


def test_undated_past_clock_rolls_to_tomorrow() -> None:
    result = _resolve("5pm", datetime(2026, 7, 10, 18, 0, tzinfo=_EASTERN))

    assert result.target == datetime(2026, 7, 11, 17, 0, tzinfo=_EASTERN)
    assert "tomorrow, Sat Jul 11" in result.target_display


def test_today_past_clock_is_error() -> None:
    with pytest.raises(ValueError, match="not in the future"):
        _resolve("today 5pm", datetime(2026, 7, 10, 18, 0, tzinfo=_EASTERN))


def test_tomorrow_and_iso_date_are_explicit() -> None:
    now = datetime(2026, 7, 10, 18, 0, tzinfo=_EASTERN)

    assert _resolve("tomorrow 9am", now).target == datetime(
        2026, 7, 11, 9, 0, tzinfo=_EASTERN
    )
    assert _resolve("2026-07-12 09:00", now).target == datetime(
        2026, 7, 12, 9, 0, tzinfo=_EASTERN
    )


@pytest.mark.parametrize("raw", ["2026-02-30 09:00", "7/12 9am", "25:00"])
def test_invalid_values_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        _resolve(raw, datetime(2026, 1, 1, 8, 0, tzinfo=_EASTERN))


def test_configured_timezone_drives_resolution_and_preview() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 7, 10, 12, 0, tzinfo=pacific)

    result = _resolve_override_until("5pm", timezone=pacific, clock=_clock(now))

    assert result.target.hour == 17
    assert result.timezone_display == "America/Los_Angeles"
    assert result.target.tzname() == "PDT"


def test_nonexistent_dst_wall_time_is_rejected() -> None:
    now = datetime(2026, 3, 7, 12, 0, tzinfo=_EASTERN)

    with pytest.raises(ValueError, match="does not exist"):
        _resolve("2026-03-08 02:30", now)


def test_ambiguous_dst_wall_time_requires_offset() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=_EASTERN)

    with pytest.raises(ValueError, match=r"occurs twice.*-04:00 or -05:00"):
        _resolve("2026-11-01 01:30", now)


def test_ambiguous_dst_offsets_select_distinct_instants() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=_EASTERN)

    first = _resolve("2026-11-01T01:30-04:00", now)
    second = _resolve("2026-11-01T01:30-05:00", now)

    assert second.expires_at - first.expires_at == 3600
    assert first.target.utcoffset() != second.target.utcoffset()


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_modal_live_preview_and_submit() -> None:
    dismissed: list[object] = []
    now = datetime(2026, 7, 10, 14, 42, tzinfo=_EASTERN)

    async with _TestApp().run_test() as pilot:
        modal = OverrideUntilModal(timezone=_EASTERN, clock=_clock(now))
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        preview = modal.query_one("#override-until-preview", Static)
        assert "America/New_York" in preview.content
        input_widget = modal.query_one("#override-until-input", Input)
        input_widget.value = "5pm"
        await pilot.pause()
        assert preview.has_class("until-valid")
        assert "Fri Jul 10" in preview.content
        await pilot.press("enter")
        await pilot.pause()

    assert len(dismissed) == 1
    assert isinstance(dismissed[0], ResolvedOverrideUntil)


async def test_modal_error_stays_open_and_escape_goes_back() -> None:
    dismissed: list[object] = []
    now = datetime(2026, 7, 10, 18, 0, tzinfo=_EASTERN)

    async with _TestApp().run_test() as pilot:
        modal = OverrideUntilModal(timezone=_EASTERN, clock=_clock(now))
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        modal.query_one("#override-until-input", Input).value = "today 5pm"
        await pilot.pause()
        preview = modal.query_one("#override-until-preview", Static)
        assert preview.has_class("until-error")
        await pilot.press("enter")
        await pilot.pause()
        assert pilot.app.screen is modal
        await pilot.press("escape")
        await pilot.pause()

    assert dismissed == [OVERRIDE_UNTIL_BACK]
