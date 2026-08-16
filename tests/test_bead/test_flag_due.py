"""The shared removal-urgency predicate every flag-rendering surface uses."""

from __future__ import annotations

from datetime import date

import pytest

from sase.bead.flag_due import flag_removal_due
from sase.bead.model import FlagRecord

RECORD = FlagRecord(
    key="demo_key", remove_by_date="2026-12-01", remove_by_release="0.19.0"
)


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
    assert flag_removal_due(RECORD, today=today, release=release) == expected


def test_release_comparison_ignores_prerelease_suffix() -> None:
    record = FlagRecord(
        key="demo_key",
        remove_by_date="2026-12-01",
        remove_by_release="0.19.0-rc.1",
    )

    assert flag_removal_due(record, today=date(2026, 1, 1), release="0.19.0") == "soon"
