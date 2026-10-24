"""Attributable perf and prompt-state evidence for ``tui_freeze_report``.

Phase interaction-evidence (epic sase-1nf.14.1) owns the perf-input and
workload side of the reporter. Stall/heartbeat/GC acceptance stays in
``_tui_freeze_report_acceptance.py``; this module reads ``tui_jk.jsonl``
perf samples plus ``prompt_activity`` rows and answers three questions:

- Which navigation samples belong to this instance (and which legacy rows
  cannot be attributed)?
- Does the selected busy hour hold a representative, attributable
  distribution per required tab?
- How do prompt-active versus idle durations (and their GC/hitch
  observations) split, without assigning mixed heartbeat intervals
  wholesale to either state?
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any


PERF_ENV_VAR = "SASE_TUI_PERF_PATH"
BUSY_WINDOW_S = 3600.0
BUSY_DURATION_TOLERANCE_S = 120.0
BIN_S = 600.0
JK_P95_LIMIT_MS = 16.0
AGENTS_TAB = "agents"
AGENTS_FLOOR_N = 100
AGENTS_FLOOR_BINS = 4
OTHER_TAB_FLOOR_N = 30
CANDIDATE_STEP_S = 600.0
CANDIDATE_LIMIT = 5

JK_BASE_ACTIONS = frozenset({"next", "prev"})
_PANE_NAV_RE = re.compile(r"^[\w-]+\.(next|prev)$")
PANEL_ACTIONS = frozenset(
    {
        "next_agent_panel",
        "prev_agent_panel",
        "next_service_panel",
        "agents_tab_switch",
    }
)


def default_perf_path() -> Path:
    """Return the perf JSONL path (env-overridable, like the TUI writer)."""
    override = os.environ.get(PERF_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / ".sase" / "perf" / "tui_jk.jsonl"


def rotated_perf_path(path: Path) -> Path:
    """Return the single rotated generation kept beside *path*."""
    return Path(f"{path}.1")


def load_perf_rows(path: Path, *, include_rotated: bool = True) -> list[dict]:
    """Load perf samples plus activity rows, including rotation by default."""
    import json

    rows: list[dict] = []
    for candidate in (path, rotated_perf_path(path)) if include_rotated else (path,):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                rows.append(record)
    return rows


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def classify_action(action: object) -> str:
    """Bucket a perf action name for separate reporting.

    Only ``next``/``prev`` and verified corresponding artifact-pane action
    names (``<pane>.next`` / ``<pane>.prev``, as emitted by
    ``_begin_artifacts_navigation``) contribute to j/k. Leader (``,``-prefixed),
    prompt, and panel actions are reported separately; the rest is ``other``.
    """
    if not isinstance(action, str) or not action:
        return "other"
    if action in JK_BASE_ACTIONS or _PANE_NAV_RE.match(action):
        return "jk"
    if action.startswith(","):
        return "leader"
    if action == "prompt_space" or action.startswith("prompt"):
        return "prompt"
    if action in PANEL_ACTIONS or action.endswith("_panel"):
        return "panel"
    return "other"


def _percentile(sorted_values: list[float], rank: float) -> float | None:
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


def _iso_utc(value: float | None) -> str | None:
    if value is None:
        return None
    return (
        datetime.fromtimestamp(value, tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "n": len(values),
        "p50": _percentile(ordered, 0.5),
        "p95": _percentile(ordered, 0.95),
        "max": max(values) if values else None,
    }


def analyze_instance_perf(
    rows: list[dict],
    instance: str,
    *,
    busy_since: float | None = None,
    busy_until: float | None = None,
    required_tabs: tuple[str, ...] = (),
    coverage_start: float | None = None,
    coverage_end: float | None = None,
    activity_rows: list[dict] | None = None,
) -> dict[str, Any]:
    """Analyze attributable perf evidence for one app instance.

    *rows* is the full loaded perf log (navigation samples across
    instances); *activity_rows* carries this bucket's ``prompt_activity``
    rows from the stalls log (the telemetry writer's home for them).
    Only rows carrying this instance's ``app_instance_id`` are
    attributable; legacy rows without one are counted with an explicit
    diagnosis and never silently assigned.
    """
    tabs = [AGENTS_TAB, *[tab for tab in required_tabs if tab != AGENTS_TAB]]
    samples: list[dict] = []
    legacy_unattributed = 0
    foreign_instance = 0
    dropped_total = 0
    for row in rows:
        # A navigation sample (legacy rows have no ``event`` field).
        row_instance = row.get("app_instance_id")
        if row_instance != instance:
            if not row_instance:
                legacy_unattributed += 1
            else:
                foreign_instance += 1
            continue
        action = row.get("action")
        paint = row.get("paint_ms")
        wall = row.get("t_wall")
        if not isinstance(action, str) or not _is_number(paint):
            legacy_unattributed += 1
            continue
        if not _is_number(wall):
            # Attributable to the instance but unplaceable on the wall
            # timeline: it cannot select or support a busy window.
            legacy_unattributed += 1
            continue
        total = row.get("dropped_total")
        if isinstance(total, int) and not isinstance(total, bool):
            dropped_total = max(dropped_total, total)
        samples.append(row)
    matched_activity: list[dict] = []
    for row in activity_rows or ():
        if row.get("event") != "prompt_activity":
            continue
        if row.get("app_instance_id") == instance:
            matched_activity.append(row)
        elif not row.get("app_instance_id"):
            legacy_unattributed += 1
        else:
            foreign_instance += 1

    by_tab_action: dict[str, dict[str, list[float]]] = {}
    for row in samples:
        tab_value = row.get("tab")
        tab: str = tab_value if isinstance(tab_value, str) else "unknown"
        bucket = classify_action(row.get("action"))
        buckets = by_tab_action.setdefault(tab, {})
        buckets.setdefault(bucket, []).append(float(row["paint_ms"]))
    tab_summary = {
        tab: {bucket: _distribution(vals) for bucket, vals in buckets.items()}
        for tab, buckets in sorted(by_tab_action.items())
    }

    candidates = _candidate_windows(samples, coverage_start, coverage_end)
    busy = _validate_busy_window(
        samples,
        tabs,
        busy_since=busy_since,
        busy_until=busy_until,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        candidates=candidates,
    )
    prompt = _analyze_prompt_states(matched_activity, coverage_start, coverage_end)

    issues: list[str] = []
    if legacy_unattributed:
        issues.append(
            f"{legacy_unattributed} perf rows lack instance attribution; "
            "recapture with fixed code (legacy rows are never assigned)"
        )
    issues.extend(busy["issues"])
    issues.extend(prompt["issues"])

    targets = _perf_targets(busy, prompt, samples, matched_activity)
    statuses = [spec["status"] for spec in targets.values()]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "INCOMPLETE" in statuses:
        overall = "INCOMPLETE"
    else:
        overall = "PASS"
    return {
        "attribution": {
            "attributed_samples": len(samples),
            "legacy_unattributed_rows": legacy_unattributed,
            "foreign_instance_rows": foreign_instance,
            "dropped_samples": dropped_total or 0,
        },
        "by_tab": tab_summary,
        "activity_bins": busy["window_bins"],
        "candidate_windows": candidates,
        "busy": busy["detail"],
        "prompt": prompt["detail"],
        "targets": targets,
        "overall_status": overall,
        "issues": issues,
    }


def _window_bins(samples: list[dict], start: float, end: float) -> list[dict[str, Any]]:
    """Ten-minute activity bins over ``[start, end]`` for j/k samples."""
    bin_count = max(1, int(math.ceil((end - start) / BIN_S)))
    bins: list[dict[str, Any]] = [
        {"bin_start": _iso_utc(start + index * BIN_S), "jk_n": 0, "agents_n": 0}
        for index in range(bin_count)
    ]
    for row in samples:
        wall = float(row["t_wall"])
        if not start <= wall <= end:
            continue
        if classify_action(row.get("action")) != "jk":
            continue
        index = min(int((wall - start) // BIN_S), bin_count - 1)
        bins[index]["jk_n"] += 1
        if row.get("tab") == AGENTS_TAB:
            bins[index]["agents_n"] += 1
    return bins


def _candidate_windows(
    samples: list[dict],
    coverage_start: float | None,
    coverage_end: float | None,
) -> list[dict[str, Any]]:
    """Report candidate hourly windows and their activity, best first."""
    if coverage_start is None or coverage_end is None:
        return []
    if coverage_end - coverage_start < BUSY_WINDOW_S:
        return []
    jk_walls = sorted(
        float(row["t_wall"])
        for row in samples
        if classify_action(row.get("action")) == "jk" and _is_number(row.get("t_wall"))
    )
    agents_walls = sorted(
        float(row["t_wall"])
        for row in samples
        if classify_action(row.get("action")) == "jk"
        and row.get("tab") == AGENTS_TAB
        and _is_number(row.get("t_wall"))
    )
    latest = coverage_end - BUSY_WINDOW_S
    candidates: list[dict[str, Any]] = []
    start = coverage_start
    while start <= latest + 1e-6:
        end = start + BUSY_WINDOW_S
        windowed = [wall for wall in jk_walls if start <= wall <= end]
        windowed_agents = [wall for wall in agents_walls if start <= wall <= end]
        bins_hit = len({int((wall - start) // BIN_S) for wall in windowed_agents})
        candidates.append(
            {
                "start": _iso_utc(start),
                "end": _iso_utc(end),
                "jk_n": len(windowed),
                "agents_n": len(windowed_agents),
                "agents_bins": bins_hit,
            }
        )
        start += CANDIDATE_STEP_S
    candidates.sort(key=lambda item: (item["agents_n"], item["jk_n"]), reverse=True)
    return candidates[:CANDIDATE_LIMIT]


def _validate_busy_window(
    samples: list[dict],
    tabs: list[str],
    *,
    busy_since: float | None,
    busy_until: float | None,
    coverage_start: float | None,
    coverage_end: float | None,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate the selected busy hour and check per-tab sampling floors."""
    issues: list[str] = []
    window_bins: list[dict[str, Any]] = []
    detail: dict[str, Any] = {
        "requested_since": busy_since,
        "requested_until": busy_until,
        "valid": False,
        "reason": None,
        "tabs": {},
    }
    if (busy_since is None) != (busy_until is None):
        reason = "busy window needs both --busy-since and --busy-until"
        issues.append(reason)
        detail["reason"] = reason
        return {"detail": detail, "issues": issues, "window_bins": window_bins}
    if busy_since is None or busy_until is None:
        reason = (
            "no busy window selected; pass --busy-since/--busy-until for the "
            "observed representative hour (a quiet window is not a busy hour)"
        )
        issues.append(reason)
        detail["reason"] = reason
        return {"detail": detail, "issues": issues, "window_bins": window_bins}
    duration = busy_until - busy_since
    if abs(duration - BUSY_WINDOW_S) > BUSY_DURATION_TOLERANCE_S:
        reason = (
            f"busy window duration {duration:.1f}s is not an hour "
            f"(expected {BUSY_WINDOW_S:.0f}s)"
        )
        issues.append(reason)
        detail["reason"] = reason
        return {"detail": detail, "issues": issues, "window_bins": window_bins}
    if coverage_start is None or coverage_end is None:
        reason = "busy window cannot be contained without observed coverage"
        issues.append(reason)
        detail["reason"] = reason
        return {"detail": detail, "issues": issues, "window_bins": window_bins}
    if busy_since < coverage_start or busy_until > coverage_end:
        reason = "busy window is not contained in the observed coverage"
        issues.append(reason)
        detail["reason"] = reason
        return {"detail": detail, "issues": issues, "window_bins": window_bins}

    windowed = [
        row
        for row in samples
        if busy_since <= float(row["t_wall"]) <= busy_until
        and classify_action(row.get("action")) == "jk"
    ]
    window_bins = _window_bins(samples, busy_since, busy_until)
    detail["window"] = {
        "start": _iso_utc(busy_since),
        "end": _iso_utc(busy_until),
        "jk_n": len(windowed),
    }
    tab_results: dict[str, Any] = {}
    sufficient = True
    for tab in tabs:
        vals = sorted(
            float(row["paint_ms"]) for row in windowed if row.get("tab") == tab
        )
        floor = AGENTS_FLOOR_N if tab == AGENTS_TAB else OTHER_TAB_FLOOR_N
        bins_hit = (
            sum(1 for entry in window_bins if entry["agents_n"] > 0)
            if (tab == AGENTS_TAB)
            else None
        )
        entry: dict[str, Any] = {"distribution": _distribution(vals)}
        if tab == AGENTS_TAB:
            entry["bins_hit"] = bins_hit
            entry["bins_floor"] = AGENTS_FLOOR_BINS
            if len(vals) < floor or (bins_hit or 0) < AGENTS_FLOOR_BINS:
                entry["sufficient"] = False
                sufficient = False
                issues.append(
                    f"Agents busy-hour floor not met: {len(vals)} samples "
                    f"(need {floor}) across {bins_hit} ten-minute bins "
                    f"(need {AGENTS_FLOOR_BINS})"
                )
            else:
                entry["sufficient"] = True
        elif len(vals) < floor:
            entry["sufficient"] = False
            sufficient = False
            issues.append(
                f"tab {tab!r} busy-hour floor not met: {len(vals)} samples "
                f"(need {floor})"
            )
        else:
            entry["sufficient"] = True
        tab_results[tab] = entry
    detail["tabs"] = tab_results
    detail["valid"] = sufficient
    if not sufficient and detail["reason"] is None:
        detail["reason"] = "per-tab sampling floors not met"
    return {"detail": detail, "issues": issues, "window_bins": window_bins}


def _analyze_prompt_states(
    activity_rows: list[dict],
    coverage_start: float | None,
    coverage_end: float | None,
) -> dict[str, Any]:
    """Reconstruct prompt-active versus idle durations from transitions."""
    issues: list[str] = []
    ordered = sorted(
        (row for row in activity_rows if _is_number(row.get("t_wall"))),
        key=lambda row: float(row["t_wall"]),
    )
    if coverage_start is None or coverage_end is None:
        detail = {
            "active_s": None,
            "idle_s": None,
            "modal_s": None,
            "unknown_s": None,
            "transitions": len(ordered),
            "reason": "no observed coverage to split",
        }
        issues.append("prompt coverage cannot be split without observed coverage")
        return {"detail": detail, "issues": issues}
    current = "unknown"
    cursor = coverage_start
    totals = {"prompt_active": 0.0, "prompt_idle": 0.0, "modal": 0.0, "unknown": 0.0}
    for row in ordered:
        wall = float(row["t_wall"])
        if wall < coverage_start:
            current = _activity_state(row)
            continue
        if wall > coverage_end:
            break
        totals[_bucket_state(current)] += max(0.0, wall - cursor)
        cursor = wall
        current = _activity_state(row)
    totals[_bucket_state(current)] += max(0.0, coverage_end - cursor)
    split: dict[str, Any] = {
        "active_s": round(totals["prompt_active"], 3),
        "idle_s": round(totals["prompt_idle"], 3),
        "modal_s": round(totals["modal"], 3),
        "unknown_s": round(totals["unknown"], 3),
        "transitions": len(ordered),
        "reason": None,
    }
    if not ordered:
        issues.append("no prompt activity evidence for this instance (unknown state)")
        split["reason"] = "missing starting state and transition coverage"
    elif totals["unknown"] > 0 and ordered[0].get("transition") != "initial":
        issues.append("leading prompt state is unknown (no initial activity row)")
    return {"detail": split, "issues": issues}


def _activity_state(row: dict) -> str:
    state = row.get("state")
    return state if isinstance(state, str) and state else "unknown"


def _bucket_state(state: str) -> str:
    if state == "prompt_active":
        return "prompt_active"
    if state == "prompt_idle":
        return "prompt_idle"
    if state in ("modal_open", "modal_active"):
        return "modal"
    return "unknown"


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


def _perf_targets(
    busy: dict[str, Any],
    prompt: dict[str, Any],
    samples: list[dict],
    activity_rows: list[dict],
) -> dict[str, dict[str, Any]]:
    detail = busy["detail"]
    tabs = detail.get("tabs") or {}
    agents = tabs.get(AGENTS_TAB) or {}
    distribution = agents.get("distribution") or {}
    agents_n = distribution.get("n", 0)
    agents_p95 = distribution.get("p95")
    if not detail.get("valid") or not agents.get("sufficient"):
        jk_status = "INCOMPLETE"
        jk_reason = detail.get("reason") or (
            "no attributable representative Agents distribution"
        )
    elif agents_p95 is not None and agents_p95 >= JK_P95_LIMIT_MS:
        jk_status = "FAIL"
        jk_reason = None
    elif agents_p95 is not None:
        jk_status = "PASS"
        jk_reason = None
    else:
        jk_status = "INCOMPLETE"
        jk_reason = "no attributable representative Agents distribution"
    other_tabs: dict[str, Any] = {}
    for tab, entry in tabs.items():
        if tab == AGENTS_TAB:
            continue
        entry_dist = entry.get("distribution") or {}
        entry_p95 = entry_dist.get("p95")
        if not entry.get("sufficient"):
            other_tabs[tab] = "INCOMPLETE"
        elif entry_p95 is not None and entry_p95 >= JK_P95_LIMIT_MS:
            other_tabs[tab] = "FAIL"
        else:
            other_tabs[tab] = "PASS"
    if any(status == "FAIL" for status in other_tabs.values()):
        jk_status = "FAIL"
        jk_reason = None
    elif any(status == "INCOMPLETE" for status in other_tabs.values()):
        jk_status = "INCOMPLETE"
        if jk_reason is None:
            jk_reason = "a declared tab lacks an attributable distribution"
    prompt_detail = prompt["detail"]
    if prompt_detail.get("unknown_s") is None:
        prompt_status = "INCOMPLETE"
        prompt_reason = prompt_detail.get("reason")
    elif not activity_rows:
        prompt_status = "INCOMPLETE"
        prompt_reason = "missing starting state and transition coverage"
    else:
        prompt_status = "PASS"
        prompt_reason = None
    return {
        "jk_p95": _target(
            jk_status,
            value={
                "agents_n": agents_n,
                "agents_p95_ms": agents_p95,
                "tabs": other_tabs,
            },
            limit=JK_P95_LIMIT_MS,
            label="Agents j/k p95 < 16 ms (attributable busy-hour distribution)",
            reason=jk_reason,
        ),
        "busy_hour": _target(
            "PASS" if detail.get("valid") else "INCOMPLETE",
            value=detail.get("window"),
            limit={
                "span_s": BUSY_WINDOW_S,
                "agents_n": AGENTS_FLOOR_N,
                "agents_bins": AGENTS_FLOOR_BINS,
                "other_tab_n": OTHER_TAB_FLOOR_N,
            },
            label="representative busy hour with per-tab sampling floors",
            reason=detail.get("reason"),
        ),
        "prompt_activity": _target(
            prompt_status,
            value={
                "active_s": prompt_detail.get("active_s"),
                "idle_s": prompt_detail.get("idle_s"),
                "modal_s": prompt_detail.get("modal_s"),
                "unknown_s": prompt_detail.get("unknown_s"),
                "transitions": prompt_detail.get("transitions"),
            },
            limit=None,
            label="attributed prompt-active versus idle durations",
            reason=prompt_reason,
        ),
    }
