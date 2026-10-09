"""Unit tests for the A1 history-independence gate in bench_bead_scale."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf.bench_bead_scale import evaluate_gate  # noqa: E402


def _corpora(lo_ops: dict[str, float], hi_ops: dict[str, float]) -> list[dict]:
    def _entry(scale: float, meds: dict[str, float]) -> dict:
        return {
            "scale": scale,
            "ops": {
                name: {"median_ms": med, "p95_ms": med} for name, med in meds.items()
            },
        }

    return [_entry(1.0, lo_ops), _entry(4.0, hi_ops)]


GATE_OPS = {
    "ready": 10.0,
    "list_active_page": 25.0,
    "show_detail_open": 7.0,
    "note_append": 20.0,
    "update": 20.0,
    "tui_cached": 15.0,
}


def test_gate_passes_on_flat_corpora() -> None:
    rows, code = evaluate_gate(
        _corpora(GATE_OPS, dict(GATE_OPS)), tolerance=0.10, allowed_misses=set()
    )
    assert code == 0
    assert rows and all(row["status"] == "pass" for row in rows)


def test_gate_fails_ratio_miss() -> None:
    hi = dict(GATE_OPS)
    hi["update"] = 60.0
    rows, code = evaluate_gate(
        _corpora(GATE_OPS, hi), tolerance=0.10, allowed_misses=set()
    )
    assert code == 1
    by_id = {row["criterion"]: row["status"] for row in rows}
    assert by_id["ratio:update"] == "fail"
    assert by_id["ratio:ready"] == "pass"


def test_gate_known_miss_stays_nonfatal_but_reported() -> None:
    hi = dict(GATE_OPS)
    hi["update"] = 60.0
    rows, code = evaluate_gate(
        _corpora(GATE_OPS, hi), tolerance=0.10, allowed_misses={"ratio:update"}
    )
    assert code == 0
    by_id = {row["criterion"]: row["status"] for row in rows}
    assert by_id["ratio:update"] == "known-miss"


def test_gate_fails_absolute_miss() -> None:
    hi = dict(GATE_OPS)
    hi["tui_cached"] = 250.0
    rows, code = evaluate_gate(
        _corpora(GATE_OPS, hi), tolerance=0.10, allowed_misses=set()
    )
    assert code == 1
    by_id = {row["criterion"]: row["status"] for row in rows}
    assert by_id["abs:tui-nochange"] == "fail"


def test_gate_errors_without_two_scales() -> None:
    rows, code = evaluate_gate(
        _corpora(GATE_OPS, GATE_OPS)[:1], tolerance=0.10, allowed_misses=set()
    )
    assert code == 2
    assert rows[0]["status"] == "error"
