"""Unit tests for the launch latency regression checker."""

from __future__ import annotations

from tests.perf.check_agent_launch_regression import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_REPORT_PATH,
    REPO_ROOT,
    ScenarioGate,
    check_scenarios,
)


def _payload(**medians: float) -> dict[str, object]:
    return {
        "scenarios": {name: {"median_ms": median} for name, median in medians.items()}
    }


def test_default_artifact_paths_live_under_sdd_tales() -> None:
    expected_dir = REPO_ROOT / "sdd" / "tales" / "202605" / "perf_artifacts"

    assert DEFAULT_BASELINE_PATH == expected_dir / "agent_launch_phase1_baseline.json"
    assert DEFAULT_REPORT_PATH == expected_dir / "agent_launch_regression_check.json"


def test_check_scenarios_passes_under_absolute_and_ratio_thresholds() -> None:
    results = check_scenarios(
        current=_payload(model_fanout=20.0, plain_prompt=5.0),
        baseline=_payload(model_fanout=2000.0, plain_prompt=1.0),
        gates=(
            ScenarioGate("model_fanout", max_baseline_ratio=0.25),
            ScenarioGate("plain_prompt", max_median_ms=100.0),
        ),
    )

    assert all(result.passed for result in results)


def test_check_scenarios_fails_when_fanout_approaches_sleep_baseline() -> None:
    results = check_scenarios(
        current=_payload(model_fanout=800.0),
        baseline=_payload(model_fanout=2000.0),
        gates=(ScenarioGate("model_fanout", max_baseline_ratio=0.25),),
    )

    assert not results[0].passed
    assert "Phase 1 baseline" in results[0].failures[0]


def test_check_scenarios_reports_missing_current_scenario() -> None:
    results = check_scenarios(
        current=_payload(),
        baseline=_payload(model_fanout=2000.0),
        gates=(ScenarioGate("model_fanout", max_baseline_ratio=0.25),),
    )

    assert not results[0].passed
    assert "current median unavailable" in results[0].failures
