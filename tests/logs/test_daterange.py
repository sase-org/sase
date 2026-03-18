"""Tests for sase.logs.daterange."""

from datetime import datetime
from unittest.mock import patch

import pytest
from sase.logs.daterange import _parse_datepoint, parse_daterange
from sase.sase_utils import EASTERN_TZ


class TestParseDatepoint:
    def test_yymmdd(self) -> None:
        result = _parse_datepoint("260318")
        assert result == datetime(2026, 3, 18, 0, 0, 0, tzinfo=EASTERN_TZ)

    def test_yymmddhhmmss(self) -> None:
        result = _parse_datepoint("260318143000")
        assert result == datetime(2026, 3, 18, 14, 30, 0, tzinfo=EASTERN_TZ)

    def test_relative_negative(self) -> None:
        fake_now = datetime(2026, 3, 18, 15, 30, 0, tzinfo=EASTERN_TZ)
        with patch("sase.logs.daterange.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            result = _parse_datepoint("-7d")
        assert result == datetime(2026, 3, 11, 0, 0, 0, tzinfo=EASTERN_TZ)

    def test_relative_zero(self) -> None:
        fake_now = datetime(2026, 3, 18, 15, 30, 0, tzinfo=EASTERN_TZ)
        with patch("sase.logs.daterange.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            result = _parse_datepoint("0d")
        assert result == datetime(2026, 3, 18, 0, 0, 0, tzinfo=EASTERN_TZ)

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid date point"):
            _parse_datepoint("foobar")

    def test_whitespace_stripped(self) -> None:
        result = _parse_datepoint("  260318  ")
        assert result == datetime(2026, 3, 18, 0, 0, 0, tzinfo=EASTERN_TZ)


class TestParseDaterange:
    def test_range_with_dots(self) -> None:
        start, end = parse_daterange("260315..260318")
        assert start == datetime(2026, 3, 15, 0, 0, 0, tzinfo=EASTERN_TZ)
        assert end == datetime(2026, 3, 18, 23, 59, 59, tzinfo=EASTERN_TZ)

    def test_single_value_means_start_to_now(self) -> None:
        fake_now = datetime(2026, 3, 18, 15, 30, 0, tzinfo=EASTERN_TZ)
        with patch("sase.logs.daterange.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            start, end = parse_daterange("-7d")
        assert start == datetime(2026, 3, 11, 0, 0, 0, tzinfo=EASTERN_TZ)
        assert end == fake_now

    def test_reversed_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Start date .* is after end date"):
            parse_daterange("260318..260315")

    def test_end_date_only_gets_end_of_day(self) -> None:
        """When end is date-only (midnight), it should be set to 23:59:59."""
        start, end = parse_daterange("260315..260318")
        assert end.hour == 23
        assert end.minute == 59
        assert end.second == 59
