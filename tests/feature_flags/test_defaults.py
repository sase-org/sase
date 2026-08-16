"""Tests for flag scaffolding defaults."""

from __future__ import annotations

from datetime import date

import pytest

from sase.feature_flags.defaults import default_flag_record
from sase.feature_flags.models import FeatureFlagError


def test_default_flag_record_uses_today_plus_ninety_and_minor_plus_two() -> None:
    record = default_flag_record(
        "demo_flag", today=date(2026, 8, 16), version="0.16.3+9.gdeadbee"
    )

    assert record.key == "demo_flag"
    assert record.remove_by_date == "2026-11-14"
    assert record.remove_by_release == "0.18.0"


def test_default_flag_record_honors_remove_by_override() -> None:
    record = default_flag_record(
        "demo_flag",
        today=date(2026, 8, 16),
        version="0.16.0",
        remove_by="2026-12-01/0.19.0",
    )

    assert record.remove_by_date == "2026-12-01"
    assert record.remove_by_release == "0.19.0"


def test_default_flag_record_rejects_missing_slash() -> None:
    with pytest.raises(FeatureFlagError, match="YYYY-MM-DD"):
        default_flag_record(
            "demo_flag",
            today=date(2026, 8, 16),
            version="0.16.0",
            remove_by="2026-12-01",
        )
