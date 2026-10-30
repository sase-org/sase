"""Evidence validation and target verdicts for ``tui_freeze_report``.

The diagnostic reporter remains tolerant of historical JSONL. Acceptance is
deliberately stricter: it uses paired heartbeat endpoints, verifies each
interval, and keeps missing evidence separate from measured failures.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


HEARTBEAT_INTERVAL_S = 300.0
HEARTBEAT_INTERVAL_TOLERANCE_S = 2.0
# A skipped heartbeat yields at least about twice the cadence, so this bound
# cannot bridge one. Intervals past the on-time tolerance but at or below this
# bound stay valid when window_s and uptime_s still agree.
HEARTBEAT_MISSING_GAP_S = 1.5 * HEARTBEAT_INTERVAL_S
STARTUP_WARMUP_S = 20 * 60.0
FOUR_HOURS_S = 4 * 60 * 60.0
RSS_GROWTH_LIMIT_BYTES = 500_000_000
IDLE_P95_LIMIT_S = 0.5
GC_SHARE_LIMIT = 0.03
HITCH_SHARE_LIMIT = 0.005
NEAR_INPUT_MAX_S = 2.0
JK_P95_LIMIT_MS = 16.0
NEAR_INPUT_TRIGGERS = frozenset({"automatic", "backstop", "rss_backstop"})


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _time_value(value: object) -> float | None:
    if _is_number(value):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _row_ts(row: dict) -> float | None:
    return _time_value(row.get("ts", row.get("timestamp")))


def _iso_utc(value: float | None) -> str | None:
    if value is None:
        return None
    return (
        datetime.fromtimestamp(value, tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _percentile(sorted_values: list[float], rank: float) -> float | None:
    """Linear interpolation at rank * (n - 1); callers pass sorted values."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = rank * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return (
        sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
    )


def _target(
    status: str,
    *,
    value: object,
    limit: object,
    label: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "pass": True if status == "PASS" else False if status == "FAIL" else None,
        "value": value,
        "limit": limit,
        "label": label,
        "reason": reason,
    }


def _overall_status(targets: dict[str, dict[str, Any]]) -> str:
    statuses = {target["status"] for target in targets.values()}
    if "FAIL" in statuses:
        return "FAIL"
    if "INCOMPLETE" in statuses:
        return "INCOMPLETE"
    return "PASS"


def _startup_record(
    startups: list[dict], instance: str
) -> tuple[dict | None, float | None]:
    matching = [
        row
        for row in startups
        if row.get("event") == "tui_startup" and row.get("app_instance_id") == instance
    ]
    matching.sort(key=lambda row: _row_ts(row) or float("inf"))
    if not matching:
        return None, None
    record = matching[0]
    return record, _row_ts(record)


def _validate_counter_row(row: dict, index: int) -> list[str]:
    issues: list[str] = []
    generations = row.get("gc_generations")
    if not isinstance(generations, dict) or not generations:
        issues.append(f"heartbeat {index}: missing gc_generations counters")
    else:
        for generation, stats in generations.items():
            if not isinstance(stats, dict):
                issues.append(f"heartbeat {index}: malformed generation {generation}")
                continue
            count = stats.get("count")
            total = stats.get("total_s")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                issues.append(
                    f"heartbeat {index}: invalid generation {generation} count"
                )
            if not _is_number(total) or float(total) < 0:
                issues.append(
                    f"heartbeat {index}: invalid generation {generation} total_s"
                )
            maximum = stats.get("max_s")
            if maximum is not None and (not _is_number(maximum) or float(maximum) < 0):
                issues.append(
                    f"heartbeat {index}: invalid generation {generation} max_s"
                )
    for field in (
        "loop_hitch_seconds",
        "loop_suppressed_seconds",
    ):
        value = row.get(field)
        if not _is_number(value) or float(value) < 0:
            issues.append(f"heartbeat {index}: invalid {field}")
    for field in ("loop_hitch_episodes", "loop_suppressed_episodes"):
        value = row.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(f"heartbeat {index}: invalid {field}")
    total_episodes = row.get("loop_hitch_episodes")
    suppressed_episodes = row.get("loop_suppressed_episodes")
    if (
        isinstance(total_episodes, int)
        and not isinstance(total_episodes, bool)
        and isinstance(suppressed_episodes, int)
        and not isinstance(suppressed_episodes, bool)
        and suppressed_episodes > total_episodes
    ):
        issues.append(f"heartbeat {index}: suppressed hitch count exceeds total")
    return issues


def _validate_endpoint(row: dict, index: int) -> list[str]:
    issues: list[str] = []
    for field in ("rss_bytes", "vmswap_bytes", "uptime_s"):
        value = row.get(field)
        if not _is_number(value) or float(value) < 0:
            issues.append(f"heartbeat {index}: invalid {field}")
    return issues


def _pair_gc_totals(
    pairs: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, int]]:
    seconds: dict[str, float] = {}
    counts: dict[str, int] = {}
    for pair in pairs:
        row = pair["right"]
        generations = row.get("gc_generations")
        if not isinstance(generations, dict):
            continue
        for generation, stats in generations.items():
            if not isinstance(stats, dict):
                continue
            total = stats.get("total_s")
            count = stats.get("count")
            if _is_number(total):
                key = str(generation)
                seconds[key] = seconds.get(key, 0.0) + float(total)
            if isinstance(count, int) and not isinstance(count, bool):
                key = str(generation)
                counts[key] = counts.get(key, 0) + count
    return seconds, counts


def _pause_interval(row: dict) -> tuple[float, float] | None:
    start = _time_value(row.get("start_ts"))
    duration = row.get("duration_s")
    if start is None or not _is_number(duration) or float(duration) < 0:
        return None
    return start, start + float(duration)


def _recovered_hitches(rows: list[dict]) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for row in rows:
        if row.get("event") != "tui_hitch_recovered":
            continue
        end = _row_ts(row)
        duration = row.get("duration_seconds")
        if end is None or not _is_number(duration) or float(duration) < 0:
            late = (
                bool(row.get("late")) or row.get("detected_by") == "watchdog_lateness"
            )
            episodes.append(
                {"row": row, "start": None, "end": end, "late": late, "valid": False}
            )
            continue
        start = end - float(duration)
        late = bool(row.get("late")) or row.get("detected_by") == "watchdog_lateness"
        episodes.append(
            {"row": row, "start": start, "end": end, "late": late, "valid": True}
        )
    return episodes


def analyze_acceptance(
    rows: list[dict],
    startups: list[dict],
    instance: str,
    *,
    requested_since: float | None,
    requested_until: float | None,
    since_tolerance_s: float = 0.0,
    until_tolerance_s: float = 0.0,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> dict[str, Any]:
    """Return one instance's evidence diagnostics and target verdicts."""
    startup, startup_ts = _startup_record(startups, instance)
    issues: list[str] = []
    if startup is None or startup_ts is None:
        issues.append("missing startup provenance for this app instance")
    elif (
        len(
            [
                row
                for row in startups
                if row.get("event") == "tui_startup"
                and row.get("app_instance_id") == instance
            ]
        )
        > 1
    ):
        issues.append("multiple startup rows use this app instance ID")

    heartbeat_rows = sorted(
        (
            row
            for row in rows
            if row.get("event") == "tui_memory_heartbeat" and _row_ts(row) is not None
        ),
        key=lambda row: _row_ts(row) or 0.0,
    )
    if startup is not None and _is_number(startup.get("pid")):
        startup_pid = int(startup["pid"])
        if any(
            _is_number(row.get("pid")) and int(row["pid"]) != startup_pid
            for row in heartbeat_rows
        ):
            issues.append("heartbeat PID differs from startup provenance")

    warmup_until = startup_ts + STARTUP_WARMUP_S if startup_ts is not None else None
    first_heartbeat_ts = _row_ts(heartbeat_rows[0]) if heartbeat_rows else None
    lower = warmup_until if warmup_until is not None else first_heartbeat_ts
    # ISO CLI boundaries carry microsecond precision. This tolerance admits
    # endpoint rounding only and is deliberately too small to bridge a poll.
    lower_tolerance = 0.0
    if requested_since is not None and (lower is None or requested_since >= lower):
        lower = requested_since
        lower_tolerance = min(max(0.0, since_tolerance_s), 0.000001)
    upper = requested_until
    upper_tolerance = min(max(0.0, until_tolerance_s), 0.000001)

    pairs: list[dict[str, Any]] = []
    pair_issues: list[str] = []
    for index in range(1, len(heartbeat_rows)):
        left = heartbeat_rows[index - 1]
        right = heartbeat_rows[index]
        left_ts = _row_ts(left)
        right_ts = _row_ts(right)
        if left_ts is None or right_ts is None:
            continue
        if lower is not None and left_ts < lower - lower_tolerance:
            continue
        if upper is not None and right_ts > upper + upper_tolerance:
            continue
        pair_errors: list[str] = []
        delta = right_ts - left_ts
        window_s = right.get("window_s")
        if delta <= 0:
            pair_errors.append(f"heartbeat {index}: non-increasing wall timestamp")
        if not _is_number(window_s) or float(window_s) <= 0:
            pair_errors.append(f"heartbeat {index}: invalid window_s")
        elif abs(delta - float(window_s)) > HEARTBEAT_INTERVAL_TOLERANCE_S:
            pair_errors.append(
                f"heartbeat {index}: window_s differs from adjacent wall times by "
                f"{abs(delta - float(window_s)):.6f}s"
            )
        if delta > HEARTBEAT_MISSING_GAP_S:
            pair_errors.append(
                f"heartbeat {index}: missing heartbeat interval ({delta:.3f}s)"
            )
        pair_errors.extend(_validate_endpoint(left, index - 1))
        pair_errors.extend(_validate_endpoint(right, index))
        pair_errors.extend(_validate_counter_row(right, index))
        left_uptime = left.get("uptime_s")
        right_uptime = right.get("uptime_s")
        if _is_number(left_uptime) and _is_number(right_uptime):
            uptime_delta = float(right_uptime) - float(left_uptime)
            if uptime_delta <= 0:
                pair_errors.append(f"heartbeat {index}: uptime reset")
            elif abs(uptime_delta - delta) > HEARTBEAT_INTERVAL_TOLERANCE_S:
                pair_errors.append(f"heartbeat {index}: uptime/window mismatch")
        pairs.append(
            {
                "left": left,
                "right": right,
                "left_ts": left_ts,
                "right_ts": right_ts,
                "delta_s": delta,
                "errors": pair_errors,
            }
        )
        pair_issues.extend(pair_errors)

    if not pairs:
        issues.append(
            "no adjacent heartbeat intervals inside the requested and warmup bounds"
        )
    issues.extend(pair_issues)
    delayed_deltas = [
        pair["delta_s"]
        for pair in pairs
        if not pair["errors"]
        and pair["delta_s"]
        > HEARTBEAT_INTERVAL_S + HEARTBEAT_INTERVAL_TOLERANCE_S
    ]
    delayed_interval_count = len(delayed_deltas)
    delayed_max_s = max(delayed_deltas) if delayed_deltas else None
    delayed_max_delay_s = (
        max(delta - HEARTBEAT_INTERVAL_S for delta in delayed_deltas)
        if delayed_deltas
        else None
    )
    actual_start = pairs[0]["left_ts"] if pairs else None
    actual_end = pairs[-1]["right_ts"] if pairs else None
    actual_span = (
        max(0.0, actual_end - actual_start)
        if actual_start is not None and actual_end is not None
        else 0.0
    )
    endpoint_rows: list[dict] = []
    if pairs:
        endpoint_rows.append(pairs[0]["left"])
        endpoint_rows.extend(pair["right"] for pair in pairs)
    contiguous = bool(pairs) and all(not pair["errors"] for pair in pairs)
    coverage_complete = contiguous and startup_ts is not None and actual_span > 0
    has_four_hours = coverage_complete and actual_span >= FOUR_HOURS_S

    gc_seconds_by_generation, gc_counts_by_generation = _pair_gc_totals(pairs)
    gc_total_s = sum(gc_seconds_by_generation.values())
    full_gc_count = sum(
        count
        for generation, count in gc_counts_by_generation.items()
        if generation.isdigit() and int(generation) >= 2
    )
    loop_hitch_s = sum(
        float(pair["right"]["loop_hitch_seconds"])
        for pair in pairs
        if _is_number(pair["right"].get("loop_hitch_seconds"))
    )
    loop_suppressed_s = sum(
        float(pair["right"]["loop_suppressed_seconds"])
        for pair in pairs
        if _is_number(pair["right"].get("loop_suppressed_seconds"))
    )
    hitch_episode_count = sum(
        int(pair["right"]["loop_hitch_episodes"])
        for pair in pairs
        if isinstance(pair["right"].get("loop_hitch_episodes"), int)
        and not isinstance(pair["right"].get("loop_hitch_episodes"), bool)
    )
    suppressed_hitch_count = sum(
        int(pair["right"]["loop_suppressed_episodes"])
        for pair in pairs
        if isinstance(pair["right"].get("loop_suppressed_episodes"), int)
        and not isinstance(pair["right"].get("loop_suppressed_episodes"), bool)
    )

    observed_start = actual_start if actual_start is not None else float("inf")
    observed_end = actual_end if actual_end is not None else float("-inf")
    pauses = [row for row in rows if row.get("event") == "tui_gc_pause"]
    pause_records_in_window: list[dict[str, Any]] = []
    pause_data_issues: list[str] = []
    for row in pauses:
        generation = row.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            continue
        interval = _pause_interval(row)
        event_ts = _row_ts(row)
        if interval is None:
            if event_ts is not None and observed_start <= event_ts <= observed_end:
                pause_data_issues.append(
                    "GC pause in observed window has no valid start_ts interval"
                )
            continue
        start, end = interval
        if end < observed_start or start > observed_end:
            continue
        pause_records_in_window.append(
            {"row": row, "start": start, "end": end, "generation": generation}
        )

    observed_full_gc_rows = [
        item
        for item in pause_records_in_window
        if item["generation"] >= 2 and observed_start <= item["end"] <= observed_end
    ]
    suppressed_pause_count = sum(
        int(item["row"].get("suppressed_count", 0))
        for item in observed_full_gc_rows
        if isinstance(item["row"].get("suppressed_count", 0), int)
        and not isinstance(item["row"].get("suppressed_count", 0), bool)
    )
    full_gc_rows_match = len(observed_full_gc_rows) == full_gc_count
    if not full_gc_rows_match:
        pause_data_issues.append(
            f"full-generation pause rows ({len(observed_full_gc_rows)}) do not match "
            f"heartbeat count ({full_gc_count})"
        )
    if suppressed_pause_count:
        pause_data_issues.append("GC pause rows report suppressed collections")
    issues.extend(pause_data_issues)
    pause_data_complete = (
        coverage_complete
        and full_gc_rows_match
        and not suppressed_pause_count
        and not pause_data_issues
    )

    idle_full_durations = sorted(
        float(item["row"]["duration_s"])
        for item in pause_records_in_window
        if item["generation"] >= 2
        and item["row"].get("trigger") == "idle"
        and _is_number(item["row"].get("duration_s"))
        and float(item["row"]["duration_s"]) >= 0
    )
    idle_p95 = _percentile(idle_full_durations, 0.95)

    near_input_rows = [
        item
        for item in observed_full_gc_rows
        if item["row"].get("trigger") in NEAR_INPUT_TRIGGERS
    ]
    known_near_input = 0
    missing_input_age = 0
    for item in near_input_rows:
        age = item["row"].get("input_age_s")
        if not _is_number(age) or float(age) < 0:
            missing_input_age += 1
        elif float(age) <= NEAR_INPUT_MAX_S:
            known_near_input += 1
    if missing_input_age:
        issues.append(
            f"{missing_input_age} relevant full-generation collections lack input age"
        )

    endpoint_trajectory = [
        {
            "ts": _row_ts(row),
            "timestamp": _iso_utc(_row_ts(row)),
            "rss_bytes": row.get("rss_bytes"),
            "vmswap_bytes": row.get("vmswap_bytes"),
        }
        for row in endpoint_rows
    ]
    valid_swap_samples = [
        float(row["vmswap_bytes"])
        for row in endpoint_rows
        if _is_number(row.get("vmswap_bytes")) and float(row["vmswap_bytes"]) >= 0
    ]
    max_swap = max(valid_swap_samples) if valid_swap_samples else None
    rss_samples = [
        (float(_row_ts(row) or 0), float(row["rss_bytes"]))
        for row in endpoint_rows
        if _is_number(row.get("rss_bytes")) and float(row["rss_bytes"]) >= 0
    ]
    rss_growth_candidates: list[dict[str, Any]] = []
    if pairs:
        valid_runs: list[list[dict[str, Any]]] = []
        current_run: list[dict[str, Any]] = []
        for pair in pairs:
            if pair["errors"]:
                if current_run:
                    valid_runs.append(current_run)
                    current_run = []
                continue
            current_run.append(pair)
        if current_run:
            valid_runs.append(current_run)
        for run in valid_runs:
            run_endpoints = [run[0]["left"]] + [pair["right"] for pair in run]
            run_rss = [
                (float(_row_ts(row) or 0), float(row["rss_bytes"]))
                for row in run_endpoints
                if _is_number(row.get("rss_bytes")) and float(row["rss_bytes"]) >= 0
            ]
            for start_index, (start_ts, start_rss) in enumerate(run_rss):
                end_index = next(
                    (
                        index
                        for index in range(start_index + 1, len(run_rss))
                        if run_rss[index][0] - start_ts >= FOUR_HOURS_S
                    ),
                    None,
                )
                if end_index is None:
                    continue
                end_ts, end_rss = run_rss[end_index]
                rss_growth_candidates.append(
                    {
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "span_s": end_ts - start_ts,
                        "start_rss_bytes": start_rss,
                        "end_rss_bytes": end_rss,
                        "growth_bytes": end_rss - start_rss,
                    }
                )
    worst_rss_window = max(
        rss_growth_candidates,
        key=lambda candidate: candidate["growth_bytes"],
        default=None,
    )
    rss_endpoint_growth = (
        rss_samples[-1][1] - rss_samples[0][1] if len(rss_samples) >= 2 else None
    )

    recoveries = _recovered_hitches(rows)
    selected_recoveries = [
        episode
        for episode in recoveries
        if episode["end"] is not None
        and observed_start <= episode["end"] <= observed_end
    ]
    recorded_episode_count = sum(
        pair["right"].get("loop_hitch_episodes", 0)
        - pair["right"].get("loop_suppressed_episodes", 0)
        for pair in pairs
        if isinstance(pair["right"].get("loop_hitch_episodes"), int)
        and not isinstance(pair["right"].get("loop_hitch_episodes"), bool)
        and isinstance(pair["right"].get("loop_suppressed_episodes"), int)
        and not isinstance(pair["right"].get("loop_suppressed_episodes"), bool)
    )
    hitch_rows_match = (
        len([episode for episode in selected_recoveries if episode["valid"]])
        == recorded_episode_count
    )
    late_episode_results: list[dict[str, Any]] = []
    for episode in recoveries:
        if not episode["late"]:
            continue
        start = episode["start"]
        end = episode["end"]
        if (
            start is not None
            and end is not None
            and (end < observed_start or start > observed_end)
        ):
            continue
        if not episode["valid"] or start is None or end is None:
            late_episode_results.append(
                {
                    "status": "unknown",
                    "reason": "missing recovery duration or timestamp",
                }
            )
            continue
        clipped_start = max(start, observed_start)
        clipped_end = min(end, observed_end)
        context_crosses_boundary = start < observed_start or end > observed_end
        if context_crosses_boundary:
            late_episode_results.append(
                {
                    "status": "unknown",
                    "start_ts": start,
                    "end_ts": end,
                    "clipped_start_ts": clipped_start,
                    "clipped_end_ts": clipped_end,
                    "reason": "late hitch crosses observed coverage boundary",
                }
            )
            continue
        overlapping = [
            item
            for item in pause_records_in_window
            if item["start"] < end and item["end"] > start
        ]
        idle_cover = any(
            item["row"].get("trigger") == "idle"
            and item["start"] <= start
            and item["end"] >= end
            for item in overlapping
        )
        non_idle_overlap = any(
            item["row"].get("trigger") != "idle" for item in overlapping
        )
        idle_overlap = any(item["row"].get("trigger") == "idle" for item in overlapping)
        if idle_cover and not non_idle_overlap:
            status = "idle_exempt"
            reason = "one idle collection covers the full late hitch"
        elif idle_cover and non_idle_overlap:
            status = "mixed"
            reason = "idle and non-idle collection intervals overlap the late hitch"
        elif idle_overlap:
            status = "partial_idle"
            reason = "idle collection covers only part of the late hitch"
        elif pause_data_complete:
            status = "unexplained"
            reason = "no idle collection covers the late hitch"
        else:
            status = "unknown"
            reason = "collection interval evidence is incomplete"
        late_episode_results.append(
            {
                "status": status,
                "start_ts": start,
                "end_ts": end,
                "reason": reason,
            }
        )

    late_violations = sum(
        episode["status"] in {"mixed", "partial_idle", "unexplained"}
        for episode in late_episode_results
    )
    late_unknown = sum(
        episode["status"] == "unknown" for episode in late_episode_results
    )
    late_ready = (
        coverage_complete
        and hitch_rows_match
        and suppressed_hitch_count == 0
        and pause_data_complete
    )
    if late_unknown:
        issues.append(
            f"{late_unknown} late hitch episodes have insufficient attribution"
        )

    gc_share = gc_total_s / actual_span if actual_span > 0 else None
    hitch_share = loop_hitch_s / actual_span if actual_span > 0 else None
    rss_growth = worst_rss_window["growth_bytes"] if worst_rss_window else None
    rss_ready = worst_rss_window is not None and startup_ts is not None

    coverage_status = "PASS" if has_four_hours else "INCOMPLETE"
    coverage_reason = (
        None
        if has_four_hours
        else ("need one gap-free, post-warmup four-hour heartbeat span")
    )
    targets = {
        "coverage": _target(
            coverage_status,
            value={"span_s": actual_span, "contiguous": contiguous},
            limit={"span_s": FOUR_HOURS_S, "contiguous": True},
            label="gap-free post-warmup coverage >= 4 h",
            reason=coverage_reason,
        ),
        "idle_p95": _target(
            "FAIL"
            if idle_p95 is not None and idle_p95 > IDLE_P95_LIMIT_S
            else (
                "PASS" if idle_p95 is not None and pause_data_complete else "INCOMPLETE"
            ),
            value=idle_p95,
            limit=IDLE_P95_LIMIT_S,
            label="idle full-generation p95 <= 500 ms",
            reason=None
            if idle_p95 is not None and pause_data_complete
            else "missing or incomplete full-generation idle pause evidence",
        ),
        "gc_share": _target(
            "FAIL"
            if gc_share is not None and gc_share >= GC_SHARE_LIMIT
            else (
                "PASS" if gc_share is not None and coverage_complete else "INCOMPLETE"
            ),
            value=gc_share,
            limit=GC_SHARE_LIMIT,
            label="total GC < 3% of observed wall time",
            reason=None
            if gc_share is not None and coverage_complete
            else "incomplete paired heartbeat counters",
        ),
        "hitch_share": _target(
            "FAIL"
            if hitch_share is not None and hitch_share >= HITCH_SHARE_LIMIT
            else (
                "PASS"
                if hitch_share is not None and coverage_complete
                else "INCOMPLETE"
            ),
            value=hitch_share,
            limit=HITCH_SHARE_LIMIT,
            label="loop hitches < 0.5% of observed wall time",
            reason=None
            if hitch_share is not None and coverage_complete
            else "incomplete paired hitch counters",
        ),
        "near_input_gen2": _target(
            "FAIL"
            if known_near_input
            else (
                "PASS"
                if not missing_input_age and pause_data_complete
                else "INCOMPLETE"
            ),
            value={
                "near_input": known_near_input,
                "missing_input_age": missing_input_age,
            },
            limit={"near_input": 0, "age_s": NEAR_INPUT_MAX_S},
            label="no automatic/backstop full GC within 2 s of input",
            reason=None
            if known_near_input or (not missing_input_age and pause_data_complete)
            else "missing input age or full-generation collection evidence",
        ),
        "late_hitches": _target(
            "FAIL"
            if late_violations
            else ("PASS" if late_ready and late_unknown == 0 else "INCOMPLETE"),
            value={
                "episodes": len(late_episode_results),
                "idle_exempt": sum(
                    item["status"] == "idle_exempt" for item in late_episode_results
                ),
                "violations": late_violations,
                "unknown": late_unknown,
                "episodes_detail": late_episode_results,
            },
            limit={"unexplained": 0},
            label="no late hitch outside a fully attributable idle collection",
            reason=None
            if late_ready and late_unknown == 0
            else "late hitch or collection interval evidence is incomplete",
        ),
        "rss_growth": _target(
            "FAIL"
            if rss_growth is not None and rss_growth >= RSS_GROWTH_LIMIT_BYTES
            else ("PASS" if rss_ready else "INCOMPLETE"),
            value=rss_growth,
            limit=RSS_GROWTH_LIMIT_BYTES,
            label="worst RSS endpoint growth < 500,000,000 B over 4 h",
            reason=None
            if rss_ready
            else "no contiguous four-hour RSS span with startup provenance",
        ),
        "vmswap": _target(
            "FAIL"
            if max_swap is not None and max_swap > 0
            else ("PASS" if max_swap == 0 and coverage_complete else "INCOMPLETE"),
            value={
                "max_bytes": max_swap,
                "last_bytes": endpoint_rows[-1].get("vmswap_bytes")
                if endpoint_rows
                else None,
            },
            limit={"max_bytes": 0},
            label="VmSwap remains zero across observed heartbeats",
            reason=None
            if max_swap is not None
            and max_swap > 0
            or (max_swap == 0 and coverage_complete)
            else "missing or incomplete VmSwap trajectory",
        ),
        "jk_p95": _target(
            "INCOMPLETE",
            value=None,
            limit=JK_P95_LIMIT_MS,
            label="Agents j/k p95 < 16 ms",
            reason="this reporter has no attributable perf-path input",
        ),
    }

    if not pause_data_complete:
        issues.extend(issue for issue in pause_data_issues if issue not in issues)
    if not hitch_rows_match:
        issues.append(
            f"recovered hitch rows ({len([episode for episode in selected_recoveries if episode['valid']])}) "
            f"do not match heartbeat recorded episode count ({recorded_episode_count})"
        )
    if suppressed_hitch_count:
        issues.append("heartbeat reports suppressed hitch episodes")

    actual_gens = sorted(
        gc_counts_by_generation, key=lambda value: (not value.isdigit(), value)
    )
    provenance = {
        "instance_id": instance,
        "startup_timestamp": _row_ts(startup) if startup else None,
        "startup_timestamp_iso": _iso_utc(_row_ts(startup)) if startup else None,
        "pid": startup.get("pid") if startup else None,
        "source_revision": startup.get("source_revision") if startup else None,
        "sase_version": startup.get("sase_version") if startup else None,
        "initial_tab": startup.get("initial_tab") if startup else None,
        "python_versions": sorted(
            {
                str(row.get("python_version"))
                for row in heartbeat_rows
                if isinstance(row.get("python_version"), str)
            }
        ),
    }
    coverage = {
        "requested_since": since_raw,
        "requested_since_epoch": requested_since,
        "requested_since_tolerance_s": since_tolerance_s,
        "requested_until": until_raw,
        "requested_until_epoch": requested_until,
        "requested_until_tolerance_s": until_tolerance_s,
        "warmup_s": STARTUP_WARMUP_S,
        "warmup_until_epoch": warmup_until,
        "warmup_until": _iso_utc(warmup_until),
        "actual_start_epoch": actual_start,
        "actual_start": _iso_utc(actual_start),
        "actual_end_epoch": actual_end,
        "actual_end": _iso_utc(actual_end),
        "actual_span_s": actual_span,
        "heartbeat_endpoint_count": len(endpoint_rows),
        "interval_count": len(pairs),
        "interval_counter_policy": "later endpoint counters only; first endpoint counters are outside the selected span",
        "valid_interval_count": sum(not pair["errors"] for pair in pairs),
        "invalid_interval_count": sum(bool(pair["errors"]) for pair in pairs),
        "delayed_interval_count": delayed_interval_count,
        "delayed_max_s": delayed_max_s,
        "delayed_max_delay_s": delayed_max_delay_s,
        "contiguous": contiguous,
        "complete": coverage_complete,
        "four_hour_span": has_four_hours,
        "issues": sorted(set(issues)),
        "interval_errors": [
            {
                "left_ts": pair["left_ts"],
                "right_ts": pair["right_ts"],
                "errors": pair["errors"],
            }
            for pair in pairs
            if pair["errors"]
        ],
    }
    counts = {
        "input_rows": len(rows),
        "heartbeat_rows_in_instance": len(heartbeat_rows),
        "paired_intervals": len(pairs),
        "full_generation_collections": full_gc_count,
        "full_generation_pause_rows": len(observed_full_gc_rows),
        "idle_full_generation_pause_rows": len(idle_full_durations),
        "eligible_near_input_rows": len(near_input_rows),
        "late_hitch_recoveries_in_window": len(selected_recoveries),
        "suppressed_hitch_episodes": suppressed_hitch_count,
        "suppressed_hitch_seconds": loop_suppressed_s,
    }
    return {
        "instance": instance,
        "provenance": provenance,
        "coverage": coverage,
        "counts": counts,
        "metrics": {
            "quantile": "linear interpolation at rank p*(n-1), sorted ascending",
            "gc_total_s": gc_total_s,
            "gc_seconds_by_generation": gc_seconds_by_generation,
            "gc_counts_by_generation": gc_counts_by_generation,
            "gc_share": gc_share,
            "loop_hitch_seconds": loop_hitch_s,
            "loop_suppressed_seconds": loop_suppressed_s,
            "hitch_share": hitch_share,
            "idle_full_generation_p95_s": idle_p95,
            "rss_first_bytes": endpoint_rows[0].get("rss_bytes")
            if endpoint_rows
            else None,
            "rss_last_bytes": endpoint_rows[-1].get("rss_bytes")
            if endpoint_rows
            else None,
            "rss_endpoint_growth_bytes": rss_endpoint_growth,
            "rss_worst_four_hour_window": worst_rss_window,
            "vmswap_max_bytes": max_swap,
            "vmswap_trajectory": endpoint_trajectory,
            "generation_keys_observed": actual_gens,
        },
        "targets": targets,
        "overall_status": _overall_status(targets),
    }


def empty_acceptance(
    instance: str, *, since_raw: str | None, until_raw: str | None
) -> dict[str, Any]:
    """Create a structured INCOMPLETE result when selection has no matching rows."""
    targets = {
        name: _target(
            "INCOMPLETE",
            value=None,
            limit=None,
            label=name,
            reason="no rows in selected window",
        )
        for name in (
            "coverage",
            "idle_p95",
            "gc_share",
            "hitch_share",
            "near_input_gen2",
            "late_hitches",
            "rss_growth",
            "vmswap",
            "jk_p95",
        )
    }
    return {
        "instance": instance,
        "provenance": {"instance_id": instance},
        "coverage": {
            "requested_since": since_raw,
            "requested_until": until_raw,
            "actual_start_epoch": None,
            "actual_end_epoch": None,
            "actual_span_s": 0.0,
            "interval_count": 0,
            "contiguous": False,
            "complete": False,
            "four_hour_span": False,
            "issues": ["no rows in selected window"],
        },
        "counts": {
            "input_rows": 0,
            "heartbeat_rows_in_instance": 0,
            "paired_intervals": 0,
        },
        "metrics": {},
        "targets": targets,
        "overall_status": "INCOMPLETE",
    }


def aggregate_status(results: dict[str, dict[str, Any]]) -> str:
    if not results:
        return "INCOMPLETE"
    return _overall_status(
        {
            f"{instance}:{target_name}": target
            for instance, result in results.items()
            for target_name, target in result["targets"].items()
        }
    )
