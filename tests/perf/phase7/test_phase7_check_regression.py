"""Tests for the Phase 7E regression-floor checker (sase-1e.5).

These tests cover the pure comparison logic and the baseline-loader. The
end-to-end ``run_floor_check`` flow is exercised by ``just
phase7-perf-check``; running the actual harnesses in the default test
suite would be too slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perf.phase7_check_regression import (
    DEFAULT_BASELINE_PATH,
    _AnchorSpec,
    _check_anchor,
    _extract_medians,
    load_baseline,
)


def _make_spec(
    *,
    must_beat_python: bool = True,
    surface: str = "parse_project_bytes",
    workload: str = "golden_myproj",
    scenario: str = "facade",
    rust_med: float = 1.0e-4,
    py_med: float = 2.0e-4,
) -> _AnchorSpec:
    return _AnchorSpec(
        anchor_id=f"{surface}.{workload}.{scenario}",
        surface=surface,
        workload=workload,
        scenario=scenario,
        phase7b_python_median_s=py_med,
        phase7b_rust_median_s=rust_med,
        must_beat_python=must_beat_python,
        rationale="test fixture",
    )


class TestLoadBaseline:
    def test_committed_baseline_loads(self) -> None:
        factor, anchors, raw = load_baseline(DEFAULT_BASELINE_PATH)
        assert factor > 1.0
        assert len(anchors) >= 1
        # Every anchor must map to a known harness mapping in the checker;
        # if a future agent renames a surface and forgets to update the
        # mapping, the public entry point's ValueError catches it. This
        # test ensures the committed baseline does not already trip that.
        from tests.perf.phase7_check_regression import _HARNESS_FOR_SURFACE

        unknown = [a.surface for a in anchors if a.surface not in _HARNESS_FOR_SURFACE]
        assert unknown == [], (
            f"baseline references surfaces with no harness mapping: {unknown}"
        )
        assert raw["schema_version"] == 1
        override_anchor = next(
            a
            for a in anchors
            if a.anchor_id
            == "notification_store.synthetic_5k.notification_modal_dismiss_burst"
        )
        assert override_anchor.rust_slowdown_factor_override == pytest.approx(1.6)
        assert "runner IO variance" in override_anchor.rust_slowdown_factor_reason

    def test_rejects_unknown_schema_version(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "schema_version": 99,
                    "tolerance": {"rust_slowdown_factor": 1.4},
                    "anchors": [],
                }
            )
        )
        with pytest.raises(ValueError):
            load_baseline(bad)


class TestCheckAnchor:
    def test_passes_when_rust_under_ceiling_and_beats_python(self) -> None:
        spec = _make_spec()
        result = _check_anchor(
            spec=spec,
            rust_med=1.05e-4,  # under 1.4 * 1e-4 = 1.4e-4
            py_med=1.9e-4,
            rust_slowdown_factor=1.4,
            notes=[],
        )
        assert result.passed
        assert result.failures == ()

    def test_fails_when_rust_exceeds_absolute_ceiling(self) -> None:
        spec = _make_spec()
        result = _check_anchor(
            spec=spec,
            rust_med=1.5e-4,  # above 1.4 * 1e-4
            py_med=2.0e-4,
            rust_slowdown_factor=1.4,
            notes=[],
        )
        assert not result.passed
        assert any("absolute floor" in f for f in result.failures)

    def test_per_anchor_slowdown_override_only_changes_that_anchor(self) -> None:
        spec = _make_spec()
        override_spec = _AnchorSpec(
            anchor_id=spec.anchor_id,
            surface=spec.surface,
            workload=spec.workload,
            scenario=spec.scenario,
            phase7b_python_median_s=spec.phase7b_python_median_s,
            phase7b_rust_median_s=spec.phase7b_rust_median_s,
            must_beat_python=spec.must_beat_python,
            rationale=spec.rationale,
            rust_slowdown_factor_override=1.6,
            rust_slowdown_factor_reason="known CI variance",
        )

        default_result = _check_anchor(
            spec=spec,
            rust_med=1.5e-4,
            py_med=2.0e-4,
            rust_slowdown_factor=1.4,
            notes=[],
        )
        override_result = _check_anchor(
            spec=override_spec,
            rust_med=1.5e-4,
            py_med=2.0e-4,
            rust_slowdown_factor=1.4,
            notes=[],
        )

        assert not default_result.passed
        assert override_result.passed
        assert override_result.rust_slowdown_factor_used == pytest.approx(1.6)
        assert any(
            "per-anchor rust_slowdown_factor" in n for n in override_result.notes
        )

    def test_fails_when_must_beat_python_and_rust_loses(self) -> None:
        spec = _make_spec(must_beat_python=True)
        result = _check_anchor(
            spec=spec,
            rust_med=1.1e-4,  # under absolute ceiling
            py_med=1.0e-4,  # but slower than python
            rust_slowdown_factor=1.4,
            notes=[],
        )
        assert not result.passed
        assert any("must_beat_python" in f for f in result.failures)

    def test_passes_when_must_beat_python_false_and_rust_slower(self) -> None:
        # apply_status_update-style anchor: don't enforce relative win.
        spec = _make_spec(must_beat_python=False)
        result = _check_anchor(
            spec=spec,
            rust_med=1.1e-4,
            py_med=1.0e-4,
            rust_slowdown_factor=1.4,
            notes=[],
        )
        assert result.passed

    def test_fails_when_rust_median_missing(self) -> None:
        spec = _make_spec()
        result = _check_anchor(
            spec=spec,
            rust_med=None,
            py_med=2.0e-4,
            rust_slowdown_factor=1.4,
            notes=["scenario missing"],
        )
        assert not result.passed
        assert any("rust median unavailable" in f for f in result.failures)
        assert "scenario missing" in result.notes


class TestExtractMedians:
    def test_returns_medians_when_present(self) -> None:
        spec = _make_spec()
        by_surface = {
            "parse_project_bytes": {
                "workloads": [
                    {
                        "label": "golden_myproj",
                        "baseline": {
                            "facade": {"count": 20, "median_us": 200.0},
                        },
                        "candidate": {
                            "facade": {"count": 20, "median_us": 100.0},
                        },
                    }
                ]
            }
        }
        rust, py, notes = _extract_medians(by_surface=by_surface, spec=spec)
        assert rust == pytest.approx(1.0e-4)
        assert py == pytest.approx(2.0e-4)
        assert notes == []

    def test_query_corpus_anchor_compares_against_python_batch_facade(self) -> None:
        spec = _make_spec(
            surface="evaluate_query_many",
            workload="synthetic_1000_specs",
            scenario="persistent_query_keystroke",
            rust_med=6.0e-5,
            py_med=3.0e-3,
        )
        by_surface = {
            "evaluate_query_many": {
                "workloads": [
                    {
                        "label": "synthetic_1000_specs",
                        "baseline": {
                            "facade": {"count": 20, "median_ms": 3.0},
                        },
                        "candidate": {
                            "persistent_query_keystroke": {
                                "count": 20,
                                "median_ms": 0.06,
                            },
                        },
                    }
                ]
            }
        }
        rust, py, notes = _extract_medians(by_surface=by_surface, spec=spec)
        assert rust == pytest.approx(6.0e-5)
        assert py == pytest.approx(3.0e-3)
        assert notes == []

    def test_records_missing_workload(self) -> None:
        spec = _make_spec(workload="missing_workload")
        by_surface = {"parse_project_bytes": {"workloads": []}}
        rust, py, notes = _extract_medians(by_surface=by_surface, spec=spec)
        assert rust is None
        assert py is None
        assert any("workload" in n for n in notes)

    def test_records_missing_surface(self) -> None:
        spec = _make_spec(surface="not_routed_yet")
        rust, py, notes = _extract_medians(by_surface={}, spec=spec)
        assert rust is None
        assert py is None
        assert any("surface" in n for n in notes)
