"""Tests for parsing reset hints out of provider usage-limit messages."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sase.llm_provider.usage_limit_config import parse_reset_hint


class TestParseResetHint:
    def test_resets_with_zone(self) -> None:
        now = 1755302400.0
        expires_at, hint = parse_reset_hint(
            "You've hit your weekly limit · resets 8pm (America/New_York)",
            now=now,
        )
        assert expires_at is not None
        assert expires_at > now
        assert hint == "8pm (America/New_York)"

    def test_resets_without_zone_uses_local_timezone(self) -> None:
        with patch("sase.core.time.get_timezone", return_value=ZoneInfo("UTC")):
            expires_at, hint = parse_reset_hint("resets 11:30pm", now=1755302400.0)
        assert expires_at is not None
        assert hint == "11:30pm"

    def test_resets_in_duration_minutes(self) -> None:
        now = 1000.0
        expires_at, hint = parse_reset_hint("try again in 5m", now=now)
        assert expires_at == now + 5 * 60 + 60  # grace buffer
        assert hint == "5m"

    def test_resets_in_compound_duration(self) -> None:
        now = 1000.0
        expires_at, hint = parse_reset_hint("resets in 2h 15m", now=now)
        assert expires_at == now + (2 * 3600 + 15 * 60) + 60
        assert hint == "2h 15m"

    def test_rolls_forward_when_time_already_passed_today(self) -> None:
        tz = ZoneInfo("UTC")
        now_dt = datetime(2026, 1, 1, 23, 0, 0, tzinfo=tz)
        now = now_dt.timestamp()
        with patch("sase.core.time.get_timezone", return_value=tz):
            expires_at, hint = parse_reset_hint("resets 1am", now=now)
        assert expires_at is not None
        assert hint == "1am"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert resolved.day == 2
        assert resolved.hour == 1

    def test_unparseable_text_returns_none(self) -> None:
        assert parse_reset_hint("no reset info here", now=1000.0) == (None, None)

    def test_unknown_zone_does_not_fall_back_to_local_time(self) -> None:
        # An explicit but unrecognized zone must not be silently reinterpreted
        # via the local-timezone form.
        expires_at, hint = parse_reset_hint("resets 8pm (Not/AZone)", now=1000.0)
        assert expires_at is None
        assert hint is None

    def test_documented_resets_at_example_now_parses(self) -> None:
        # docs/configuration.md's example for honor_reset_hint; broadening the
        # anchor to accept "at"/"on" is what makes this finally true.
        with patch("sase.core.time.get_timezone", return_value=ZoneInfo("UTC")):
            expires_at, hint = parse_reset_hint("resets at 8pm", now=1755302400.0)
        assert expires_at is not None
        assert hint == "8pm"

    def test_reset_at_with_zone_broadened_anchor(self) -> None:
        expires_at, hint = parse_reset_hint(
            "Your limit will reset at 3am (America/New_York)", now=1755302400.0
        )
        assert expires_at is not None
        assert hint == "3am (America/New_York)"

    def test_codex_bare_time_only_uses_broadened_anchor(self) -> None:
        with patch("sase.core.time.get_timezone", return_value=ZoneInfo("UTC")):
            expires_at, hint = parse_reset_hint(
                "Try again at 6:38 AM.", now=1755302400.0
            )
        assert expires_at is not None
        assert hint == "6:38am"

    def test_codex_ordinal_date_with_year_uppercase_meridiem(self) -> None:
        tz = ZoneInfo("UTC")
        now = datetime(2026, 8, 17, 6, 0, 0, tzinfo=tz).timestamp()
        with patch("sase.core.time.get_timezone", return_value=tz):
            expires_at, hint = parse_reset_hint(
                "or try again at Aug 20th, 2026 6:38 AM.", now=now
            )
        assert expires_at is not None
        assert hint == "Aug 20th, 2026 6:38 AM"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.year, resolved.month, resolved.day) == (2026, 8, 20)
        assert (resolved.hour, resolved.minute) == (6, 38)

    def test_claude_weekly_limit_month_name_with_zone_and_minutes(self) -> None:
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 17, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "You've hit your weekly limit · resets Aug 20, 6:38 am (America/New_York)",
            now=now,
        )
        assert expires_at is not None
        assert hint == "Aug 20, 6:38 am (America/New_York)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.year, resolved.month, resolved.day) == (2026, 8, 20)
        assert (resolved.hour, resolved.minute) == (6, 38)

    def test_claude_compact_fw_meridiem_no_space_no_minutes(self) -> None:
        # Live 2.1.235 ``fW`` spelling. Would fail if the month-date regex
        # required ``\s+`` before ``am|pm``.
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 19, 15, 43, 56, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "resets Aug 22, 8pm (America/New_York)", now=now
        )
        assert expires_at is not None
        assert hint == "Aug 22, 8pm (America/New_York)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.year, resolved.month, resolved.day) == (2026, 8, 22)
        assert (resolved.hour, resolved.minute) == (20, 0)

    def test_claude_compact_fw_meridiem_with_minutes(self) -> None:
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 17, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "resets Aug 20, 6:38am (America/New_York)", now=now
        )
        assert expires_at is not None
        assert hint == "Aug 20, 6:38am (America/New_York)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.hour, resolved.minute) == (6, 38)

    def test_claude_compact_fw_meridiem_no_minutes(self) -> None:
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 17, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "resets Aug 20, 6am (America/New_York)", now=now
        )
        assert expires_at is not None
        assert hint == "Aug 20, 6am (America/New_York)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.hour, resolved.minute) == (6, 0)

    def test_unanchored_month_date_parses_only_when_allowed(self) -> None:
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 19, 15, 43, 56, tzinfo=tz).timestamp()
        text = "You've hit your weekly limit · Aug 22, 8pm (America/New_York)"
        assert parse_reset_hint(text, now=now) == (None, None)
        expires_at, hint = parse_reset_hint(text, now=now, allow_unanchored=True)
        assert expires_at is not None
        assert hint is not None
        assert "Aug 22" in hint
        assert "8pm" in hint
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.year, resolved.month, resolved.day, resolved.hour) == (
            2026,
            8,
            22,
            20,
        )

    def test_incidental_date_does_not_parse_with_public_default(self) -> None:
        assert parse_reset_hint("Aug 22, 8pm (America/New_York)", now=1755302400.0) == (
            None,
            None,
        )

    def test_unresolvable_keyword_form_does_not_run_unanchored_fallback(self) -> None:
        assert parse_reset_hint(
            "resets Aug 32nd, 2026 6:38 AM",
            now=1755302400.0,
            allow_unanchored=True,
        ) == (None, None)

    def test_claude_month_name_with_zone_no_minutes(self) -> None:
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 17, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "resets Aug 20, 6 am (America/New_York)", now=now
        )
        assert expires_at is not None
        assert hint == "Aug 20, 6 am (America/New_York)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.month, resolved.day, resolved.hour, resolved.minute) == (
            8,
            20,
            6,
            0,
        )

    def test_claude_month_name_with_zone_and_explicit_year(self) -> None:
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 12, 30, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "resets Aug 20, 2027, 6:38 am (America/New_York)", now=now
        )
        assert expires_at is not None
        assert hint == "Aug 20, 2027, 6:38 am (America/New_York)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.year, resolved.month, resolved.day) == (2027, 8, 20)

    def test_claude_billing_iso_with_bare_utc(self) -> None:
        tz = ZoneInfo("UTC")
        now = datetime(2026, 8, 17, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint(
            "spend limit reached (monthly; resets 2026-08-20 06:38 UTC)", now=now
        )
        assert expires_at is not None
        assert hint == "2026-08-20 06:38 UTC"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert (resolved.year, resolved.month, resolved.day) == (2026, 8, 20)
        assert (resolved.hour, resolved.minute) == (6, 38)

    def test_resets_iso_without_zone_uses_local_timezone(self) -> None:
        tz = ZoneInfo("UTC")
        now = datetime(2026, 8, 17, tzinfo=tz).timestamp()
        with patch("sase.core.time.get_timezone", return_value=tz):
            expires_at, hint = parse_reset_hint("resets 2026-08-20 06:38", now=now)
        assert expires_at is not None
        assert hint == "2026-08-20 06:38"

    def test_month_name_unresolvable_day_returns_none(self) -> None:
        # A matched-but-invalid payload (day 32) must not fall through to a
        # lower-priority form.
        expires_at, hint = parse_reset_hint(
            "resets Aug 32nd, 2026 6:38 AM", now=1755302400.0
        )
        assert expires_at is None
        assert hint is None

    def test_year_inference_picks_same_year(self) -> None:
        tz = ZoneInfo("UTC")
        now = datetime(2026, 8, 17, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint("resets Aug 20, 6:38 am (UTC)", now=now)
        assert expires_at is not None
        assert hint == "Aug 20, 6:38 am (UTC)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert resolved.year == 2026

    def test_year_inference_rolls_to_next_year(self) -> None:
        tz = ZoneInfo("UTC")
        now = datetime(2026, 12, 30, 6, 0, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint("resets Jan 2, 6:38 am (UTC)", now=now)
        assert expires_at is not None
        assert hint == "Jan 2, 6:38 am (UTC)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert resolved.year == 2027

    def test_year_inference_keeps_recent_past_instead_of_rolling_forward(
        self,
    ) -> None:
        tz = ZoneInfo("UTC")
        now = datetime(2026, 8, 17, 10, 5, 0, tzinfo=tz).timestamp()
        expires_at, hint = parse_reset_hint("resets Aug 17, 10:00 am (UTC)", now=now)
        assert expires_at is not None
        assert hint == "Aug 17, 10:00 am (UTC)"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert resolved == datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz)
        assert abs(expires_at - now) < 3600
