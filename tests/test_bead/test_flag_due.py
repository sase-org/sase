"""The shared removal-urgency predicate every flag-rendering surface uses."""

from __future__ import annotations

from datetime import date

import pytest

from sase.bead.flag_due import flag_removal_due

REMOVE_BY_DATE = "2026-12-01"
REMOVE_BY_RELEASE = "0.19.0"


@pytest.mark.parametrize(
    ("today", "release", "expected"),
    [
        (date(2026, 1, 1), "0.10.0", "live"),
        (date(2026, 12, 2), "0.10.0", "soon"),
        (date(2026, 1, 1), "0.19.0", "soon"),
        (date(2026, 1, 1), "0.20.0", "soon"),
        (date(2026, 12, 2), "0.19.0", "due"),
        (date(2026, 12, 1), "0.20.0", "due"),
    ],
)
def test_state_requires_both_thresholds_for_due(
    today: date, release: str, expected: str
) -> None:
    assert (
        flag_removal_due(
            REMOVE_BY_DATE, REMOVE_BY_RELEASE, today=today, release=release
        )
        == expected
    )


def test_release_comparison_ignores_prerelease_suffix() -> None:
    assert (
        flag_removal_due(
            "2026-12-01", "0.19.0-rc.1", today=date(2026, 1, 1), release="0.19.0"
        )
        == "soon"
    )
