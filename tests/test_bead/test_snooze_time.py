"""Parsing of the snooze duration and wake-time forms every surface accepts."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sase.bead.snooze_time import (
    SnoozeTimeError,
    parse_snooze_request,
    parse_snooze_until,
)
from tests.test_bead.snooze_gate_test_helpers import WAKE_TIME


@pytest.mark.parametrize(
    ("text", "expected_plus_ones"),
    [("3d", None), ("2h", None), ("1h30m", None), ("3d +2", 2), ("30m  +1", 1)],
)
def test_snooze_request_parses_every_accepted_form(
    text: str, expected_plus_ones: int | None
) -> None:
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    request = parse_snooze_request(text, now=now)

    assert request.plus_ones == expected_plus_ones
    assert datetime.fromisoformat(request.until) > now


def test_snooze_request_resolves_days_and_absolute_timestamps() -> None:
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    assert parse_snooze_until("3d", now=now) == (now + timedelta(days=3)).isoformat()
    assert (
        parse_snooze_until("1d2h", now=now)
        == (now + timedelta(days=1, hours=2)).isoformat()
    )
    assert parse_snooze_until(WAKE_TIME, now=now) == WAKE_TIME


def test_snooze_request_attaches_the_configured_timezone_to_a_naive_timestamp() -> None:
    """A naive ISO-8601 timestamp is read in the configured zone, not refused."""
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    request = parse_snooze_request("2026-08-09T09:00:00", now=now)

    assert request.until == WAKE_TIME


@pytest.mark.parametrize(
    "text",
    [
        "",
        "threeish days",
        "3 days",
        "0m",
        "2026-08-01T09:00:00-04:00",
        "3d +0",
        "3d ++2",
    ],
)
def test_snooze_request_rejects_unusable_input(text: str) -> None:
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    with pytest.raises(SnoozeTimeError) as exc_info:
        parse_snooze_request(text, now=now)

    assert "accepted forms" in str(exc_info.value)


def test_snooze_request_matches_the_cli_seconds_resolution() -> None:
    """Every surface stores the same shape of wake instant, to the second."""
    now = datetime.fromisoformat("2026-08-06T09:00:00.123456-04:00")

    request = parse_snooze_request("2h", now=now)

    assert request.until == "2026-08-06T11:00:00-04:00"
