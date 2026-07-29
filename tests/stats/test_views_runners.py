from dataclasses import FrozenInstanceError
from zoneinfo import ZoneInfo

import pytest

from sase.stats.views import build_statistics_views
from tests.stats._views_payloads import activity_payload, run_payload


def test_runner_view_maps_summary_distribution_and_timezone_slices() -> None:
    views = build_statistics_views(
        run_payload(),
        activity_payload(),
        timezone=ZoneInfo("UTC"),
        current_runner_limit=4,
    )

    runners = views.runners
    assert runners.available is True
    assert (runners.start_ts, runners.end_ts) == (0.0, 7_200.0)
    assert runners.peak_runners == 3
    assert runners.peak_seconds == 600.0
    assert runners.average_runners == 1.25
    assert runners.busy_seconds == 6_000.0
    assert runners.busy_share == pytest.approx(6_000 / 7_200)
    assert runners.runner_seconds == 9_000.0
    assert runners.current_limit == 4
    assert runners.malformed_rows_skipped == 1
    assert runners.invalid_intervals_skipped == 2

    # Distribution covers every observed count from zero through the peak, and
    # the conservation identities from the backend contract still hold.
    assert [row.runners for row in runners.distribution] == [0, 1, 2, 3]
    assert sum(row.seconds for row in runners.distribution) == pytest.approx(
        runners.end_ts - runners.start_ts
    )
    assert sum(
        row.runners * row.seconds for row in runners.distribution
    ) == pytest.approx(runners.runner_seconds)
    assert runners.distribution[1].share == pytest.approx(0.5)

    # Trend slices carry exact bounds, time-weighted average, and a label
    # formatted in the configured SASE timezone.
    assert [slice_.label for slice_ in runners.trend] == ["Thu 00:00", "Thu 01:00"]
    assert runners.trend[1].average_runners == 1.5
    assert runners.trend[1].peak_runners == 3


def test_runner_view_absent_payload_is_unavailable_but_keeps_current_limit() -> None:
    views = build_statistics_views(
        {"totals": {"runs": 0}},
        {},
        current_runner_limit=6,
    )

    runners = views.runners
    assert runners.available is False
    assert runners.distribution == ()
    assert runners.trend == ()
    assert runners.peak_runners == 0
    assert runners.average_runners == 0.0
    assert runners.current_limit == 6


def test_runner_emptiness_is_independent_of_launch_count() -> None:
    payload = run_payload()
    payload["totals"] = {"runs": 0}
    payload["outcomes"] = []
    payload["runners"] = {
        "start_ts": 0.0,
        "end_ts": 3_600.0,
        "peak_runners": 1,
        "peak_seconds": 1_200.0,
        "average_runners": 1 / 3,
        "busy_seconds": 1_200.0,
        "busy_share": 1 / 3,
        "runner_seconds": 1_200.0,
        "distribution": [
            {"runners": 0, "seconds": 2_400.0, "share": 2 / 3},
            {"runners": 1, "seconds": 1_200.0, "share": 1 / 3},
        ],
        "trend": [],
        "malformed_rows_skipped": 0,
        "invalid_intervals_skipped": 0,
    }

    views = build_statistics_views(payload, activity_payload())

    # A carry-in runner still renders even when the Runs view has no launches.
    assert views.empty is True
    assert views.runners.available is True
    assert [row.runners for row in views.runners.distribution] == [0, 1]


def test_runner_view_is_frozen() -> None:
    runners = build_statistics_views(run_payload(), activity_payload()).runners

    with pytest.raises(FrozenInstanceError):
        runners.peak_runners = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        runners.distribution[0].seconds = 1.0  # type: ignore[misc]
