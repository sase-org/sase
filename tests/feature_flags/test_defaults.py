"""Tests for flag scaffolding defaults."""

from __future__ import annotations

from datetime import date

import pytest

from sase.feature_flags.defaults import default_remove_by_thresholds
from sase.feature_flags.models import FeatureFlagError


def test_default_remove_by_thresholds_uses_today_plus_90_and_minor_plus_2() -> None:
    remove_by_date, remove_by_release = default_remove_by_thresholds(
        today=date(2026, 8, 16), version="0.16.3+9.gdeadbee"
    )

    assert remove_by_date == "2026-11-14"
    assert remove_by_release == "0.18.0"


def test_default_remove_by_thresholds_honors_remove_by_override() -> None:
    remove_by_date, remove_by_release = default_remove_by_thresholds(
        today=date(2026, 8, 16),
        version="0.16.0",
        remove_by="2026-12-01/0.19.0",
    )

    assert remove_by_date == "2026-12-01"
    assert remove_by_release == "0.19.0"


def test_default_remove_by_thresholds_rejects_missing_slash() -> None:
    with pytest.raises(FeatureFlagError, match="YYYY-MM-DD"):
        default_remove_by_thresholds(
            today=date(2026, 8, 16),
            version="0.16.0",
            remove_by="2026-12-01",
        )
