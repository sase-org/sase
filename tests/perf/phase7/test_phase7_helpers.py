"""Tests for the Phase 7 measurement-contract helpers.

These tests run in the default (fast) test selection because they only
exercise the metadata/summary helpers — no benchmarks are run, so they
are safe to keep out of the ``slow`` mark.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perf.phase7 import (
    BackendChoice,
    PHASE7_ARTIFACT_DIR,
    artifact_path,
    build_metadata,
    compute_speedup,
    scenario_median,
    summarize_report,
)
from tests.perf.phase7.metadata import PHASE7_PHASE_TAG


REPO_ROOT = Path(__file__).resolve().parents[3]
EXISTING_ARTIFACT = (
    REPO_ROOT / "plans/202604/perf_artifacts/bench_status_state_machine_phase4a.json"
)


class TestArtifactPath:
    def test_default_location(self) -> None:
        assert artifact_path(
            surface="parse_project_bytes",
            backend_or_summary=BackendChoice.DEFAULT_RUST,
        ) == (
            PHASE7_ARTIFACT_DIR
            / "rust_backend_phase7_parse_project_bytes_default_rust.json"
        )

    def test_summary_tag(self) -> None:
        assert (
            artifact_path(
                surface="evaluate_query_many",
                backend_or_summary=BackendChoice.SUMMARY,
            ).name
            == "rust_backend_phase7_evaluate_query_many_summary.json"
        )

    def test_custom_summary_string(self) -> None:
        assert (
            artifact_path(
                surface="sase_run_startup",
                backend_or_summary="ratio_summary",
            ).name
            == "rust_backend_phase7_sase_run_startup_ratio_summary.json"
        )

    def test_artifact_dir_override(self, tmp_path: Path) -> None:
        assert (
            artifact_path(
                surface="x",
                backend_or_summary=BackendChoice.DEFAULT_PYTHON,
                artifact_dir=tmp_path,
            ).parent
            == tmp_path
        )

    def test_rejects_empty_surface(self) -> None:
        with pytest.raises(ValueError):
            artifact_path(surface="", backend_or_summary=BackendChoice.DEFAULT_RUST)


class TestBuildMetadata:
    def test_required_fields_populated(self) -> None:
        md = build_metadata(
            tool="bench_core_parse",
            surface="parse_project_bytes",
            workload="golden_myproj",
            backend=BackendChoice.DEFAULT_RUST,
            runs=20,
            warmup=3,
        )

        d = md.as_dict()
        assert d["tool"] == "bench_core_parse"
        assert d["surface"] == "parse_project_bytes"
        assert d["workload"] == "golden_myproj"
        assert d["backend"] == "default_rust"
        assert d["runs"] == 20
        assert d["warmup"] == 3
        assert d["phase"] == PHASE7_PHASE_TAG
        # Timestamp should look like ISO-8601 UTC with trailing Z.
        assert d["timestamp"].endswith("Z")
        assert "T" in d["timestamp"]
        # Platform fields are present.
        assert d["python"]
        assert d["system"]
        assert d["machine"]
        assert d["processor"]
        # Rust-extension probe is non-fatal: either way these keys exist.
        assert "rust_available" in d
        assert "rust_module_path" in d
        assert "rust_module_version" in d

    def test_extra_round_trips_through_json(self) -> None:
        md = build_metadata(
            tool="bench_tui_trace",
            surface="sase_ace_cold_open",
            workload="synthetic_500_specs",
            backend=BackendChoice.EXPLICIT_PYTHON,
            runs=10,
            warmup=2,
            extra={"terminal": {"cols": 200, "rows": 50}},
        )

        d = md.as_dict()
        assert d["extra"] == {"terminal": {"cols": 200, "rows": 50}}

        # Must serialise as plain JSON (no enum / dataclass leakage).
        roundtrip = json.loads(json.dumps(d))
        assert roundtrip["backend"] == "explicit_python"
        assert roundtrip["extra"]["terminal"]["cols"] == 200

    def test_empty_extra_omitted_from_dict(self) -> None:
        md = build_metadata(
            tool="bench_core_query",
            surface="evaluate_query_many",
            workload="synthetic_1000_specs",
            backend=BackendChoice.DEFAULT_RUST,
            runs=20,
            warmup=3,
        )
        d = md.as_dict()
        assert "extra" not in d


class TestScenarioMedian:
    def test_handles_ms_and_us(self) -> None:
        assert scenario_median({"count": 5, "median_ms": 12.5}) == pytest.approx(0.0125)
        assert scenario_median({"count": 5, "median_us": 250.0}) == pytest.approx(
            0.000_25
        )

    def test_handles_seconds_and_ns(self) -> None:
        assert scenario_median({"count": 1, "median_s": 1.5}) == pytest.approx(1.5)
        assert scenario_median({"count": 1, "median_ns": 5_000_000.0}) == pytest.approx(
            0.005
        )

    def test_zero_count_treated_as_missing(self) -> None:
        assert scenario_median({"count": 0, "median_ms": 12.5}) is None
        assert scenario_median({"count": 0.0, "median_us": 12.5}) is None

    def test_missing_median_returns_none(self) -> None:
        assert scenario_median({"count": 5}) is None
        assert scenario_median({}) is None

    def test_non_numeric_value_returns_none(self) -> None:
        assert scenario_median({"count": 5, "median_ms": "fast"}) is None


class TestComputeSpeedup:
    def test_basic_speedup(self) -> None:
        baseline = {"count": 20, "median_ms": 10.0}
        candidate = {"count": 20, "median_ms": 4.0}
        cmp = compute_speedup(
            baseline=baseline,
            candidate=candidate,
            surface="parse_project_bytes",
            workload="synthetic_1000_specs",
            scenario="rust_facade",
        )
        assert cmp.ratio == pytest.approx(0.4)
        assert cmp.speedup == pytest.approx(2.5)
        assert cmp.percent_delta == pytest.approx(-60.0)
        assert cmp.notes == ()

    def test_baseline_missing(self) -> None:
        cmp = compute_speedup(
            baseline=None,
            candidate={"count": 5, "median_ms": 1.0},
            surface="x",
            workload="y",
            scenario="s",
        )
        assert cmp.ratio is None
        assert cmp.speedup is None
        assert "baseline missing" in cmp.notes

    def test_candidate_missing(self) -> None:
        cmp = compute_speedup(
            baseline={"count": 5, "median_ms": 1.0},
            candidate=None,
            surface="x",
            workload="y",
            scenario="s",
        )
        assert cmp.ratio is None
        assert cmp.speedup is None
        assert "candidate missing" in cmp.notes

    def test_zero_count_propagates_as_missing(self) -> None:
        cmp = compute_speedup(
            baseline={"count": 0, "median_ms": 12.5},
            candidate={"count": 5, "median_ms": 1.0},
            surface="x",
            workload="y",
            scenario="s",
        )
        assert cmp.ratio is None
        assert "baseline median unavailable" in cmp.notes

    def test_as_dict_round_trip(self) -> None:
        cmp = compute_speedup(
            baseline={"count": 20, "median_ms": 10.0},
            candidate={"count": 20, "median_ms": 4.0},
            surface="parse_project_bytes",
            workload="synthetic_1000_specs",
            scenario="rust_facade",
        )
        d = cmp.as_dict()
        json.dumps(d)  # serialisable
        assert d["ratio"] == pytest.approx(0.4)
        assert d["speedup"] == pytest.approx(2.5)


class TestSummarizeReport:
    def test_pivots_existing_phase4a_artifact(self) -> None:
        """Smoke-test the helper against a real Phase 4A JSON shape.

        Phase 7A's exit criterion is that the helper can roll up
        existing benchmark JSON without each agent re-implementing the
        pivot. We exercise it on the committed Phase 4A status-machine
        artifact so a future shape change here is caught immediately.
        """
        if not EXISTING_ARTIFACT.exists():
            pytest.skip(f"existing artifact {EXISTING_ARTIFACT} not present")

        report = json.loads(EXISTING_ARTIFACT.read_text())
        # The Phase 4A artifact has multiple workloads, each with
        # ``scenarios_python_backend`` and ``scenarios_rust_backend``.
        any_compared = False
        for workload in report["workloads"]:
            comparisons = summarize_report(
                surface="status_state_machine",
                workload=workload["label"],
                baseline_scenarios=workload.get("scenarios_python_backend"),
                candidate_scenarios=workload.get("scenarios_rust_backend"),
            )
            for cmp in comparisons:
                if cmp.ratio is not None:
                    any_compared = True
                    # Sanity bounds — Phase 4A status-machine ratios live
                    # near 1.0 (Rust facade routing only); just ensure
                    # the helper produces a finite positive number.
                    assert 0.1 < cmp.ratio < 10.0
        assert any_compared, "expected at least one scenario to produce a ratio"

    def test_includes_scenarios_unique_to_one_side(self) -> None:
        comparisons = summarize_report(
            surface="parse_project_bytes",
            workload="golden_myproj",
            baseline_scenarios={"python_direct": {"count": 5, "median_ms": 1.0}},
            candidate_scenarios={"rust_direct": {"count": 5, "median_ms": 0.4}},
        )
        names = {c.scenario for c in comparisons}
        assert names == {"python_direct", "rust_direct"}
        for c in comparisons:
            assert c.ratio is None  # one side is missing in each case
