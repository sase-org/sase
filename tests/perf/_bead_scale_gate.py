"""A1 history-independence gate for the bead scale benchmark."""

from __future__ import annotations

from typing import Any

__all__ = ["GATE_ABSOLUTE_OPS", "GATE_RATIO_OPS", "evaluate_gate"]

# A1 history-independence gate (sase-1h8.14 perf-gate). Ratio criteria
# compare the largest corpus against the smallest one measured in the same
# run, so both sides see the same host load. Absolute criteria use the
# median (the first repetition cold-builds the read model; the median of
# three is a warm read). ``list`` here is the paged active-status query
# that default ``sase bead list`` runs (list_issue_page), not the unbounded
# list_issues dump; the TUI no-change refresh is the cached snapshot path.
GATE_RATIO_OPS = (
    ("ratio:ready", "ready"),
    ("ratio:list", "list_active_page"),
    ("ratio:detail", "show_detail_open"),
    ("ratio:note", "note_append"),
    ("ratio:update", "update"),
)
GATE_ABSOLUTE_OPS = (
    # (criterion id, op, stat, ceiling_ms)
    ("abs:point-read", "show_detail_open", "median_ms", 20.0),
    ("abs:active-list", "list_active_page", "median_ms", 50.0),
    ("abs:tui-nochange", "tui_cached", "median_ms", 100.0),
)


def _stat(
    corpora: list[dict[str, Any]], scale: Any, op: str, field: str
) -> float | None:
    for corpus in corpora:
        if corpus.get("scale") == scale and op in corpus["ops"]:
            return float(corpus["ops"][op].get(field, 0.0))
    return None


def evaluate_gate(
    corpora: list[dict[str, Any]],
    *,
    tolerance: float,
    allowed_misses: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Check A1 criteria; return (rows, exit_code).

    Every criterion is always evaluated and reported. Criteria named in
    ``allowed_misses`` are recorded as known misses (with their measured
    breakdown) without failing the run; anything else that misses fails.
    Known misses must cite the bead follow-up that owns the fix, so the
    threshold is never loosened silently.
    """
    scales = sorted(
        {c["scale"] for c in corpora if c.get("scale") is not None},
        key=float,
    )
    rows: list[dict[str, Any]] = []
    if len(scales) < 2:
        rows.append(
            {
                "criterion": "gate:needs-two-scales",
                "status": "error",
                "detail": "ratio criteria need at least two --scale corpora",
            }
        )
        return rows, 2
    lo, hi = scales[0], scales[-1]
    for criterion, op in GATE_RATIO_OPS:
        lo_v = _stat(corpora, lo, op, "p95_ms")
        hi_v = _stat(corpora, hi, op, "p95_ms")
        if lo_v is None or hi_v is None:
            rows.append(
                {
                    "criterion": criterion,
                    "status": "error",
                    "detail": f"op {op!r} was not measured at both scales",
                }
            )
            continue
        ratio = (hi_v / lo_v) if lo_v > 0 else float("inf")
        ceiling = 1.0 + tolerance
        ok = ratio <= ceiling
        rows.append(
            {
                "criterion": criterion,
                "status": "pass" if ok else "fail",
                "op": op,
                "lo_scale": lo,
                "hi_scale": hi,
                "lo_p95_ms": round(lo_v, 1),
                "hi_p95_ms": round(hi_v, 1),
                "ratio": round(ratio, 3),
                "ceiling": round(ceiling, 3),
            }
        )
    check_scales = scales
    for criterion, op, field, ceiling_ms in GATE_ABSOLUTE_OPS:
        worst_scale: Any = None
        worst_val = 0.0
        missing = False
        for scale in check_scales:
            val = _stat(corpora, scale, op, field)
            if val is None:
                missing = True
                break
            if val > worst_val:
                worst_val = val
                worst_scale = scale
        if missing:
            rows.append(
                {
                    "criterion": criterion,
                    "status": "error",
                    "detail": f"op {op!r} was not measured at every scale",
                }
            )
            continue
        ok = worst_val <= ceiling_ms
        rows.append(
            {
                "criterion": criterion,
                "status": "pass" if ok else "fail",
                "op": op,
                "worst_scale": worst_scale,
                "worst_median_ms": round(worst_val, 1),
                "ceiling_ms": ceiling_ms,
            }
        )
    exit_code = 0
    for row in rows:
        if row["status"] == "error":
            exit_code = 2
        elif row["status"] == "fail" and row["criterion"] not in allowed_misses:
            exit_code = 1
    for row in rows:
        if row["status"] == "fail" and row["criterion"] in allowed_misses:
            row["status"] = "known-miss"
    return rows, exit_code
