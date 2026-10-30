"""Reconstruct witnessed activity intervals and conservatively split observations."""

from __future__ import annotations

import math
from typing import Any

try:
    from _tui_freeze_report_acceptance import (
        HEARTBEAT_INTERVAL_TOLERANCE_S,
        HEARTBEAT_MISSING_GAP_S,
    )
except ImportError:  # loaded via importlib without tools dir on sys.path
    from tools._tui_freeze_report_acceptance import (
        HEARTBEAT_INTERVAL_TOLERANCE_S,
        HEARTBEAT_MISSING_GAP_S,
    )

STATES = ("prompt_active", "prompt_idle", "modal_active", "modal_open", "unknown")


def _number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def analyze_prompt_states(
    activity_rows: list[dict],
    start: float | None,
    end: float | None,
    observations: list[dict],
) -> dict[str, Any]:
    """Only adjacent sequence/time witnesses establish an interval's state.

    A checkpoint repeats the latest sequence. A transition increments it. A
    gap invalidates the preceding interval; the new snapshot can seed the next.
    No extrapolation beyond the final witness: a lost closing transition must
    not silently turn a long capture into continuous prompt activity.
    """
    ordered = sorted(
        (row for row in activity_rows if _number(row.get("t_wall"))),
        key=lambda row: row["t_wall"],
    )
    issues: list[str] = []
    totals = dict.fromkeys(STATES, 0.0)
    segments: list[tuple[float, float, str]] = []
    if start is None or end is None or end <= start:
        return {
            "detail": {
                "active_s": None,
                "idle_s": None,
                "modal_s": None,
                "unknown_s": None,
                "transitions": len(ordered),
                "reason": "no observed coverage to split",
            },
            "issues": ["prompt coverage cannot be split without observed coverage"],
        }
    cursor = start
    for left, right in zip(ordered, ordered[1:]):
        lo, hi = max(start, left["t_wall"]), min(end, right["t_wall"])
        if hi <= lo:
            continue
        if lo > cursor:
            segments.append((cursor, lo, "unknown"))
        sequence = left.get("sequence")
        next_sequence = right.get("sequence")
        state = left.get("state")
        valid = (
            isinstance(sequence, int)
            and not isinstance(sequence, bool)
            and sequence >= 0
            and isinstance(next_sequence, int)
            and not isinstance(next_sequence, bool)
            and next_sequence == sequence + (right.get("transition") != "checkpoint")
            and state in STATES
            and state != "unknown"
            and _number(left.get("t_mono"))
            and _number(right.get("t_mono"))
            and right["t_mono"] >= left["t_mono"]
            and abs(
                (right["t_mono"] - left["t_mono"]) - (right["t_wall"] - left["t_wall"])
            )
            <= 2
        )
        if right.get("transition") == "checkpoint" and right.get("state") != state:
            valid = False
        segments.append((lo, hi, state if valid else "unknown"))
        cursor = hi
    if cursor < end:
        segments.append((cursor, end, "unknown"))
    for lo, hi, state in segments:
        totals[state] += hi - lo
    if totals["unknown"] > 0:
        issues.append(
            "prompt state unknown: missing starting/ending witness, transition sequence gap, or clock discontinuity"
        )
    detail = {
        "active_s": totals["prompt_active"],
        "idle_s": totals["prompt_idle"],
        "modal_s": totals["modal_active"] + totals["modal_open"],
        "modal_text_entry_s": totals["modal_active"],
        "unknown_s": totals["unknown"],
        "transitions": sum(row.get("transition") != "checkpoint" for row in ordered),
        "reason": issues[0] if issues else None,
        "observations": _observations(observations, segments, start, end),
    }
    return {"detail": detail, "issues": issues}


def _interval_state(
    segments: list[tuple[float, float, str]], lo: float, hi: float
) -> str:
    states = {state for start, end, state in segments if start < hi and end > lo}
    if not states or "unknown" in states:
        return "unknown"
    return next(iter(states)) if len(states) == 1 else "mixed"


def _observations(
    rows: list[dict], segments: list[tuple[float, float, str]], start: float, end: float
) -> dict[str, Any]:
    result: dict[str, Any] = {
        state: {
            "heartbeat_intervals": 0,
            "heartbeat_span_s": 0.0,
            "gc_total_s": 0.0,
            "loop_hitch_seconds": 0.0,
            "loop_suppressed_seconds": 0.0,
            "gc_pauses": 0,
            "gc_pause_s": 0.0,
            "hitch_episodes": 0,
            "hitch_episode_s": 0.0,
        }
        for state in (*STATES, "mixed")
    }
    beats = sorted(
        (
            row
            for row in rows
            if row.get("event") == "tui_memory_heartbeat" and _number(row.get("ts"))
        ),
        key=lambda row: row["ts"],
    )
    invalid = 0
    for left, right in zip(beats, beats[1:]):
        lo, hi = left["ts"], right["ts"]
        if lo < start or hi > end:
            continue
        generations = right.get("gc_generations")
        window = right.get("window_s")
        if (
            not _number(window)
            or not 0 < hi - lo <= HEARTBEAT_MISSING_GAP_S
            or abs(window - (hi - lo)) > HEARTBEAT_INTERVAL_TOLERANCE_S
            or not isinstance(generations, dict)
            or not generations
            or any(
                not isinstance(g, dict)
                or not _number(g.get("total_s"))
                or g["total_s"] < 0
                for g in generations.values()
            )
            or any(
                not _number(right.get(key)) or right[key] < 0
                for key in ("loop_hitch_seconds", "loop_suppressed_seconds")
            )
        ):
            invalid += 1
            continue
        bucket = result[_interval_state(segments, lo, hi)]
        bucket["heartbeat_intervals"] += 1
        bucket["heartbeat_span_s"] += hi - lo
        bucket["gc_total_s"] += sum(g["total_s"] for g in generations.values())
        for key in ("loop_hitch_seconds", "loop_suppressed_seconds"):
            bucket[key] += right[key]
    for row in rows:
        if row.get("event") == "tui_gc_pause":
            lo, duration = row.get("start_ts"), row.get("duration_s")
            kind = "gc_pause"
        elif row.get("event") == "tui_hitch_recovered":
            duration, hi = row.get("duration_seconds"), row.get("ts")
            lo = hi - duration if _number(hi) and _number(duration) else None
            kind = "hitch_episode"
        else:
            continue
        if not _number(lo) or not _number(duration) or duration < 0:
            continue
        hi = min(end, lo + duration)
        lo = max(start, lo)
        if hi <= lo:
            continue
        bucket = result[_interval_state(segments, lo, hi)]
        bucket[kind + "s"] += 1
        bucket[kind + "_s"] += hi - lo
    return {
        "by_state": result,
        "invalid_heartbeat_intervals": invalid,
        "note": "Heartbeat totals and emitted episodes overlap; never add them. Mixed intervals are unassigned.",
    }
