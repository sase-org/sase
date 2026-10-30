"""Acceptance evidence validation for the TUI GC reporter."""

from __future__ import annotations

from datetime import datetime, timezone, UTC

import pytest

from tools._tui_freeze_report_acceptance import analyze_acceptance, empty_acceptance


INSTANCE = "instance-a"
STARTUP_TS = 1_000.0
FIRST_HEARTBEAT_TS = STARTUP_TS + 20 * 60


def _startup(ts: float = STARTUP_TS) -> dict:
    return {
        "event": "tui_startup",
        "timestamp": datetime.fromtimestamp(ts, tz=UTC).isoformat(),
        "app_instance_id": INSTANCE,
        "pid": 41,
        "source_revision": "abc123",
        "sase_version": "1.2.3",
    }


def _heartbeat(
    ts: float,
    previous_ts: float,
    *,
    rss: int = 1_000_000_000,
    swap: int = 0,
    gc_seconds: float = 0.0,
    gc_count: int = 0,
    hitch_seconds: float = 0.0,
    hitch_episodes: int = 0,
    suppressed_hitches: int = 0,
) -> dict:
    return {
        "event": "tui_memory_heartbeat",
        "ts": ts,
        "app_instance_id": INSTANCE,
        "pid": 41,
        "uptime_s": ts - STARTUP_TS,
        "window_s": ts - previous_ts,
        "rss_bytes": rss,
        "vmswap_bytes": swap,
        "gc_generations": {
            "0": {"count": 0, "total_s": 0.0, "max_s": 0.0},
            "1": {"count": 0, "total_s": 0.0, "max_s": 0.0},
            "2": {
                "count": gc_count,
                "total_s": gc_seconds,
                "max_s": gc_seconds,
            },
        },
        "loop_hitch_seconds": hitch_seconds,
        "loop_suppressed_seconds": 0.0,
        "loop_hitch_episodes": hitch_episodes,
        "loop_suppressed_episodes": suppressed_hitches,
    }


def _analyze(
    rows: list[dict],
    *,
    startups: list[dict] | None = None,
    since: float | None = None,
    until: float | None = None,
    since_tolerance_s: float = 0.0,
    until_tolerance_s: float = 0.0,
) -> dict:
    return analyze_acceptance(
        rows,
        startups if startups is not None else [_startup()],
        INSTANCE,
        requested_since=since,
        requested_until=until,
        since_tolerance_s=since_tolerance_s,
        until_tolerance_s=until_tolerance_s,
    )


def test_first_heartbeat_counters_belong_to_pre_window_interval() -> None:
    rows = [
        _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300, gc_seconds=100.0),
        _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS, gc_seconds=1.0),
        _heartbeat(FIRST_HEARTBEAT_TS + 600, FIRST_HEARTBEAT_TS + 300, gc_seconds=2.0),
    ]

    result = _analyze(rows)

    assert result["coverage"]["interval_count"] == 2
    assert result["metrics"]["gc_total_s"] == pytest.approx(3.0)
    assert result["coverage"]["actual_span_s"] == pytest.approx(600.0)


def test_missing_heartbeat_gap_is_not_bridged_by_matching_window_s() -> None:
    rows = [
        _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300),
        _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS),
        _heartbeat(FIRST_HEARTBEAT_TS + 900, FIRST_HEARTBEAT_TS + 300),
    ]

    result = _analyze(rows)

    assert result["coverage"]["contiguous"] is False
    assert result["coverage"]["invalid_interval_count"] == 1
    assert any(
        "missing heartbeat interval" in issue for issue in result["coverage"]["issues"]
    )
    assert result["targets"]["coverage"]["status"] == "INCOMPLETE"


def test_adjacent_window_s_uses_two_second_tolerance() -> None:
    left = _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300)
    accepted = _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS)
    rejected = _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS)
    rejected["window_s"] = 300 - 2.5

    accepted_result = _analyze([left, accepted])
    rejected_result = _analyze([left, rejected])

    assert accepted_result["coverage"]["valid_interval_count"] == 1
    assert rejected_result["coverage"]["invalid_interval_count"] == 1


def test_delayed_heartbeat_with_matching_window_s_is_valid() -> None:
    left = _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300)
    right = _heartbeat(
        FIRST_HEARTBEAT_TS + 304.094, FIRST_HEARTBEAT_TS, hitch_seconds=1.0
    )
    right["window_s"] = 303.696331

    result = _analyze([left, right])

    assert result["coverage"]["valid_interval_count"] == 1
    assert result["coverage"]["contiguous"] is True
    assert result["coverage"]["delayed_interval_count"] == 1
    assert result["coverage"]["delayed_max_s"] == right["ts"] - left["ts"]


def test_slightly_late_heartbeat_with_matching_window_s_is_valid() -> None:
    left = _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300)
    right = _heartbeat(FIRST_HEARTBEAT_TS + 302.1, FIRST_HEARTBEAT_TS)

    result = _analyze([left, right])

    assert result["coverage"]["valid_interval_count"] == 1
    assert result["coverage"]["delayed_interval_count"] == 1


def test_long_gap_with_mismatched_window_s_fails_coverage() -> None:
    left = _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300)
    right = _heartbeat(FIRST_HEARTBEAT_TS + 600, FIRST_HEARTBEAT_TS)
    right["window_s"] = 300.0

    result = _analyze([left, right])

    assert result["coverage"]["contiguous"] is False
    assert result["coverage"]["invalid_interval_count"] == 1


def test_uptime_reset_is_incomplete_evidence() -> None:
    left = _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300)
    right = _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS)
    right["uptime_s"] = left["uptime_s"] - 1

    result = _analyze([left, right])

    assert result["coverage"]["contiguous"] is False
    assert any("uptime reset" in issue for issue in result["coverage"]["issues"])


def test_iso_boundary_rounding_uses_only_microsecond_tolerance() -> None:
    start = FIRST_HEARTBEAT_TS + 0.0000004
    middle = start + 300
    end = middle + 300
    rows = [
        _heartbeat(start, start - 300),
        _heartbeat(middle, start),
        _heartbeat(end, middle),
    ]

    within_precision = _analyze(
        rows,
        since=FIRST_HEARTBEAT_TS,
        until=FIRST_HEARTBEAT_TS + 600,
        since_tolerance_s=0.000001,
        until_tolerance_s=0.000001,
    )
    beyond_precision = _analyze(
        rows,
        since=FIRST_HEARTBEAT_TS + 0.000002,
        until=FIRST_HEARTBEAT_TS + 300,
        since_tolerance_s=0.000001,
        until_tolerance_s=0.000001,
    )

    assert within_precision["coverage"]["interval_count"] == 2
    assert beyond_precision["coverage"]["interval_count"] == 0


def test_swap_peak_then_fall_remains_a_failure() -> None:
    rows = [
        _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300, swap=0),
        _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS, swap=80_000_000),
        _heartbeat(FIRST_HEARTBEAT_TS + 600, FIRST_HEARTBEAT_TS + 300, swap=0),
    ]

    result = _analyze(rows)

    assert result["metrics"]["vmswap_max_bytes"] == 80_000_000
    assert result["metrics"]["vmswap_trajectory"][-1]["vmswap_bytes"] == 0
    assert result["targets"]["vmswap"]["status"] == "FAIL"


def _late_hitch_rows(
    *,
    collections: list[tuple[str, float, float]],
) -> list[dict]:
    rows = [
        _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300),
        _heartbeat(
            FIRST_HEARTBEAT_TS + 300,
            FIRST_HEARTBEAT_TS,
            gc_seconds=sum(duration for _, _, duration in collections),
            gc_count=len(collections),
            hitch_seconds=2.0,
            hitch_episodes=1,
        ),
        _heartbeat(FIRST_HEARTBEAT_TS + 600, FIRST_HEARTBEAT_TS + 300),
        {
            "event": "tui_hitch_recovered",
            "ts": FIRST_HEARTBEAT_TS + 42,
            "duration_seconds": 2.0,
            "late": True,
            "detected_by": "watchdog_lateness",
            "app_instance_id": INSTANCE,
        },
    ]
    for trigger, start_offset, duration in collections:
        rows.append(
            {
                "event": "tui_gc_pause",
                "ts": FIRST_HEARTBEAT_TS + start_offset + duration,
                "start_ts": FIRST_HEARTBEAT_TS + start_offset,
                "duration_s": duration,
                "generation": 2,
                "trigger": trigger,
                "input_age_s": 5.0,
                "suppressed_count": 0,
                "app_instance_id": INSTANCE,
            }
        )
    return rows


def test_late_hitch_requires_full_idle_collection_attribution() -> None:
    idle_only = _analyze(_late_hitch_rows(collections=[("idle", 40, 2.0)]))
    non_idle = _analyze(_late_hitch_rows(collections=[("automatic", 40, 2.0)]))
    mixed = _analyze(
        _late_hitch_rows(collections=[("idle", 40, 2.0), ("automatic", 41, 0.5)])
    )

    assert idle_only["targets"]["late_hitches"]["status"] == "PASS"
    assert non_idle["targets"]["late_hitches"]["status"] == "FAIL"
    assert mixed["targets"]["late_hitches"]["status"] == "FAIL"
    assert (
        mixed["targets"]["late_hitches"]["value"]["episodes_detail"][0]["status"]
        == "mixed"
    )


def test_late_hitch_with_partial_idle_overlap_fails() -> None:
    result = _analyze(_late_hitch_rows(collections=[("idle", 40, 1.0)]))

    assert result["targets"]["late_hitches"]["status"] == "FAIL"
    assert (
        result["targets"]["late_hitches"]["value"]["episodes_detail"][0]["status"]
        == "partial_idle"
    )


def test_boundary_crossing_late_hitch_is_unknown() -> None:
    rows = [
        _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300),
        _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS),
        _heartbeat(FIRST_HEARTBEAT_TS + 600, FIRST_HEARTBEAT_TS + 300),
        {
            "event": "tui_hitch_recovered",
            "ts": FIRST_HEARTBEAT_TS + 301,
            "duration_seconds": 3.0,
            "late": True,
            "app_instance_id": INSTANCE,
        },
    ]

    result = _analyze(
        rows,
        since=FIRST_HEARTBEAT_TS + 300,
        until=FIRST_HEARTBEAT_TS + 600,
    )

    assert result["targets"]["late_hitches"]["status"] == "INCOMPLETE"
    assert result["targets"]["late_hitches"]["value"]["unknown"] == 1


def test_decimal_rss_threshold_and_swap_trajectory_use_all_samples() -> None:
    rows = []
    timestamp = FIRST_HEARTBEAT_TS
    previous = timestamp - 300
    for index in range(49):
        rss = 1_000_000_000 + (500_000_000 if index == 48 else 0)
        swap = 0 if index != 20 else 10_000
        rows.append(_heartbeat(timestamp, previous, rss=rss, swap=swap))
        previous = timestamp
        timestamp += 300

    result = _analyze(rows)

    assert result["coverage"]["actual_span_s"] == pytest.approx(14_400.0)
    assert result["targets"]["coverage"]["status"] == "PASS"
    assert result["targets"]["rss_growth"]["limit"] == 500_000_000
    assert result["targets"]["rss_growth"]["status"] == "FAIL"
    assert result["targets"]["vmswap"]["status"] == "FAIL"


def test_missing_fields_and_no_navigation_are_incomplete_not_pass() -> None:
    first = _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300)
    later = _heartbeat(FIRST_HEARTBEAT_TS + 300, FIRST_HEARTBEAT_TS)
    later.pop("loop_hitch_seconds")
    result = _analyze([first, later])

    assert result["targets"]["hitch_share"]["status"] == "INCOMPLETE"
    assert result["targets"]["jk_p95"]["status"] == "INCOMPLETE"
    assert result["overall_status"] == "INCOMPLETE"


def test_missing_input_age_for_relevant_collection_is_incomplete() -> None:
    rows = [
        _heartbeat(FIRST_HEARTBEAT_TS, FIRST_HEARTBEAT_TS - 300),
        _heartbeat(
            FIRST_HEARTBEAT_TS + 300,
            FIRST_HEARTBEAT_TS,
            gc_seconds=0.2,
            gc_count=1,
        ),
        {
            "event": "tui_gc_pause",
            "ts": FIRST_HEARTBEAT_TS + 102,
            "start_ts": FIRST_HEARTBEAT_TS + 100,
            "duration_s": 2.0,
            "generation": 2,
            "trigger": "automatic",
            "suppressed_count": 0,
            "app_instance_id": INSTANCE,
        },
    ]

    result = _analyze(rows)

    assert result["targets"]["near_input_gen2"]["status"] == "INCOMPLETE"
    assert result["targets"]["near_input_gen2"]["value"]["missing_input_age"] == 1


def test_empty_acceptance_is_structured_incomplete() -> None:
    result = empty_acceptance(INSTANCE, since_raw="100", until_raw="200")

    assert result["overall_status"] == "INCOMPLETE"
    assert result["coverage"]["issues"] == ["no rows in selected window"]
    assert all(
        target["status"] == "INCOMPLETE" for target in result["targets"].values()
    )
