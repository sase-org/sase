"""Bucket helpers: TIMESTAMPS parsing, date and status bucketing."""

from __future__ import annotations

from datetime import datetime

from sase.ace.changespec import TimestampEntry
from sase.ace.tui.models.changespec_groups import (
    date_bucket_for_changespec,
    date_bucket_sort_index,
    latest_changespec_timestamp,
    sibling_root_for_changespec,
    status_bucket_for_changespec,
    status_sort_index,
)

from ._changespec_groups_helpers import _NOW, _cs


def _ts(
    timestamp: str, event: str = "STATUS", detail: str = "WIP -> Draft"
) -> TimestampEntry:
    return TimestampEntry(timestamp=timestamp, event_type=event, detail=detail)


# --- TIMESTAMPS parser helper ---


def test_latest_timestamp_parses_new_yymmdd_format() -> None:
    cs = _cs("a", timestamps=[_ts("260426_120000")])
    assert latest_changespec_timestamp(cs) == datetime(2026, 4, 26, 12, 0, 0)


def test_latest_timestamp_parses_old_yyyy_mm_dd_format() -> None:
    cs = _cs("a", timestamps=[_ts("2026-04-26 12:00:00")])
    assert latest_changespec_timestamp(cs) == datetime(2026, 4, 26, 12, 0, 0)


def test_latest_timestamp_picks_newest_across_hybrid_history() -> None:
    """File rows can mix old and new formats during the migration window."""
    cs = _cs(
        "a",
        timestamps=[
            _ts("2026-04-25 09:00:00"),
            _ts("260426_115959"),
            _ts("2026-04-26 11:00:00"),
        ],
    )
    assert latest_changespec_timestamp(cs) == datetime(2026, 4, 26, 11, 59, 59)


def test_latest_timestamp_ignores_malformed_entries_but_keeps_others() -> None:
    cs = _cs(
        "a",
        timestamps=[
            _ts("not-a-timestamp"),
            _ts("260426_120000"),
            _ts("999999_999999"),  # parses regex but not strptime
        ],
    )
    assert latest_changespec_timestamp(cs) == datetime(2026, 4, 26, 12, 0, 0)


def test_latest_timestamp_returns_none_when_missing() -> None:
    assert latest_changespec_timestamp(_cs("a", timestamps=None)) is None
    assert latest_changespec_timestamp(_cs("a", timestamps=[])) is None


def test_latest_timestamp_returns_none_when_all_malformed() -> None:
    cs = _cs("a", timestamps=[_ts("garbage"), _ts("also bad")])
    assert latest_changespec_timestamp(cs) is None


# --- Date bucketing ---


def test_date_bucket_today() -> None:
    cs = _cs("a", timestamps=[_ts("260426_080000")])
    assert date_bucket_for_changespec(cs, _NOW) == "Today"


def test_date_bucket_yesterday() -> None:
    cs = _cs("a", timestamps=[_ts("260425_120000")])
    assert date_bucket_for_changespec(cs, _NOW) == "Yesterday"


def test_date_bucket_this_week_within_six_days() -> None:
    cs = _cs("a", timestamps=[_ts("260422_120000")])
    assert date_bucket_for_changespec(cs, _NOW) == "This Week"


def test_date_bucket_earlier_past_week() -> None:
    cs = _cs("a", timestamps=[_ts("260418_120000")])
    assert date_bucket_for_changespec(cs, _NOW) == "Earlier"


def test_date_bucket_missing_timestamps_lands_in_earlier() -> None:
    cs = _cs("a", timestamps=None)
    assert date_bucket_for_changespec(cs, _NOW) == "Earlier"


def test_date_bucket_uses_calendar_date_not_24h_window() -> None:
    cs = _cs("a", timestamps=[_ts("260425_130000")])
    just_after_midnight = datetime(2026, 4, 26, 0, 0, 1)
    assert date_bucket_for_changespec(cs, just_after_midnight) == "Yesterday"


def test_date_bucket_sort_index_orders_buckets() -> None:
    assert date_bucket_sort_index("Today") == 0
    assert date_bucket_sort_index("Yesterday") == 1
    assert date_bucket_sort_index("This Week") == 2
    assert date_bucket_sort_index("Earlier") == 3
    # Unknown labels sort after the four known ones.
    assert date_bucket_sort_index("Whenever") == 4


# --- Status bucketing ---


def test_status_bucket_returns_literal_status_text() -> None:
    cs = _cs("a", status="Ready - (!: REVIEWERS PENDING)")
    assert status_bucket_for_changespec(cs) == "Ready - (!: REVIEWERS PENDING)"


def test_status_bucket_handles_empty_status() -> None:
    assert status_bucket_for_changespec(_cs("a", status="")) == ""


def test_status_sort_index_follows_display_order() -> None:
    """Mailed -> Ready -> WIP -> Draft -> Submitted -> Reverted -> Archived."""
    indices = [
        status_sort_index(s)[0]
        for s in (
            "Mailed",
            "Ready",
            "WIP",
            "Draft",
            "Submitted",
            "Reverted",
            "Archived",
        )
    ]
    assert indices == sorted(indices)
    assert indices == list(range(7))


def test_status_sort_index_groups_suffixed_variants_with_their_base() -> None:
    """``Ready - (...)`` sorts in the Ready slot, not at the end."""
    plain = status_sort_index("Ready")
    suffixed = status_sort_index("Ready - (!: TODO)")
    assert plain[0] == suffixed[0]
    # Different exact text → tiebreak so the sort is deterministic.
    assert plain != suffixed


def test_status_sort_index_unknown_sorts_after_known() -> None:
    known = status_sort_index("Submitted")[0]
    unknown = status_sort_index("Bogus")[0]
    assert unknown > known


# --- Sibling root ---


def test_sibling_root_strips_trailing_underscore_number() -> None:
    assert sibling_root_for_changespec(_cs("foobar_1")) == "foobar"
    assert sibling_root_for_changespec(_cs("foobar_2")) == "foobar"


def test_sibling_root_strips_legacy_double_underscore_suffix() -> None:
    assert sibling_root_for_changespec(_cs("foobar__3")) == "foobar"


def test_sibling_root_returns_name_when_no_suffix() -> None:
    assert sibling_root_for_changespec(_cs("foobar")) == "foobar"
