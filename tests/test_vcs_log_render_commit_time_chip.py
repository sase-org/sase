"""Tests for the compact commit-time chip renderer."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import sase.vcs_log.render as render_mod
from sase.vcs_log.render import build_commit_time_chip


def _chip(
    monkeypatch: pytest.MonkeyPatch,
    dt_local: datetime,
    now_local: datetime,
) -> str:
    monkeypatch.setattr(render_mod, "to_local", lambda ts: dt_local)
    return build_commit_time_chip(0, now_local=now_local).plain


def test_today_tier_includes_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    dt = datetime(2026, 8, 6, 7, 5, 54)
    now = datetime(2026, 8, 6, 9, 5, 54)

    assert _chip(monkeypatch, dt, now) == "Today 07:05:54 · 2h ago"


def test_yesterday_tier_includes_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    dt = datetime(2026, 8, 5, 21, 4, 0)
    now = datetime(2026, 8, 6, 11, 4, 0)

    assert _chip(monkeypatch, dt, now) == "Yesterday 21:04:00 · 14h ago"


def test_earlier_this_year_tier_omits_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dt = datetime(2026, 8, 6, 9, 31, 0)
    now = datetime(2026, 8, 18, 9, 31, 0)

    assert _chip(monkeypatch, dt, now) == "Aug 6 09:31 · 12d ago"


def test_previous_year_tier_omits_seconds_and_shows_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dt = datetime(2025, 8, 6, 9, 31, 0)
    now = datetime(2026, 8, 7, 9, 31, 0)

    assert _chip(monkeypatch, dt, now) == "Aug 6, 2025 09:31 · 366d ago"


@pytest.mark.parametrize(
    ("delta_seconds", "expected"),
    [
        (0, "just now"),
        (30, "30s ago"),
        (90, "1m ago"),
        (3661, "1h ago"),
        (90_000, "1d ago"),
    ],
)
def test_relative_age_ladder(
    monkeypatch: pytest.MonkeyPatch,
    delta_seconds: int,
    expected: str,
) -> None:
    dt = datetime(2026, 8, 6, 7, 0, 0)
    now = dt + timedelta(seconds=delta_seconds)

    assert _chip(monkeypatch, dt, now).endswith(f" · {expected}")


def test_future_timestamp_never_renders_negative_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dt = datetime(2026, 8, 6, 7, 0, 0)
    now = datetime(2026, 8, 6, 6, 0, 0)

    assert _chip(monkeypatch, dt, now) == "Today 07:00:00 · just now"
