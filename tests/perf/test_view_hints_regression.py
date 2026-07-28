"""Unit tests for the view-hints regression checker."""

from __future__ import annotations

from tests.perf.check_view_hints_regression import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_REPORT_PATH,
    REPO_ROOT,
    CounterGate,
    SpanGate,
    check_view_hints,
)


def _payload(
    *,
    span_ms: dict[tuple[str, str], float] | None = None,
    counters: dict[tuple[str, str], float] | None = None,
) -> dict[str, object]:
    median: dict[str, dict[str, object]] = {}
    for (step, span), value in (span_ms or {}).items():
        step_payload = median.setdefault(step, {"spans": {}, "hint_counters": {}})
        spans = step_payload["spans"]
        assert isinstance(spans, dict)
        spans[span] = {"p50_ms": value}
    for (step, counter), value in (counters or {}).items():
        step_payload = median.setdefault(step, {"spans": {}, "hint_counters": {}})
        hint_counters = step_payload["hint_counters"]
        assert isinstance(hint_counters, dict)
        hint_counters[counter] = value
    return {"median": median}


def test_default_baseline_and_report_paths_live_in_expected_locations() -> None:
    assert DEFAULT_BASELINE_PATH == (
        REPO_ROOT / "tests" / "perf" / "baselines" / "view_hints_baseline.json"
    )
    assert DEFAULT_REPORT_PATH == (
        REPO_ROOT
        / "sdd"
        / "plans"
        / "202607"
        / "perf_artifacts"
        / "view_hints_regression_check.json"
    )


def test_span_gate_passes_under_absolute_and_ratio_thresholds() -> None:
    results = check_view_hints(
        current=_payload(
            span_ms={("large_reply_first_press", "agents.view_files"): 5.0}
        ),
        baseline=_payload(
            span_ms={("large_reply_first_press", "agents.view_files"): 30.0}
        ),
        span_gates=(
            SpanGate(
                "large",
                step="large_reply_first_press",
                span="agents.view_files",
                max_ms=20.0,
                max_baseline_ratio=0.70,
            ),
        ),
        counter_gates=(),
    )

    assert all(result.passed for result in results)


def test_span_gate_fails_when_current_approaches_sync_baseline() -> None:
    results = check_view_hints(
        current=_payload(
            span_ms={("family_container_unfolded_press", "agents.view_files"): 70.0}
        ),
        baseline=_payload(
            span_ms={("family_container_unfolded_press", "agents.view_files"): 85.0}
        ),
        span_gates=(
            SpanGate(
                "family",
                step="family_container_unfolded_press",
                span="agents.view_files",
                max_baseline_ratio=0.50,
            ),
        ),
        counter_gates=(),
    )

    assert not results[0].passed
    assert "baseline ceiling" in results[0].failures[0]


def test_counter_gate_fails_when_repeat_press_rescans_text() -> None:
    results = check_view_hints(
        current=_payload(
            counters={("large_reply_repeat_press", "annotated_chars"): 102_541.0}
        ),
        baseline=_payload(
            counters={("large_reply_repeat_press", "annotated_chars"): 102_541.0}
        ),
        span_gates=(),
        counter_gates=(
            CounterGate(
                "repeat",
                step="large_reply_repeat_press",
                counter="annotated_chars",
                max_value=0.0,
            ),
        ),
    )

    assert not results[0].passed
    assert "absolute ceiling" in results[0].failures[0]


def test_counter_gate_treats_absent_auto_refresh_scan_as_zero() -> None:
    results = check_view_hints(
        current=_payload(),
        baseline=_payload(
            counters={("hint_mode_auto_refresh", "annotated_chars"): 102_541.0}
        ),
        span_gates=(),
        counter_gates=(
            CounterGate(
                "refresh",
                step="hint_mode_auto_refresh",
                counter="annotated_chars",
                max_value=0.0,
                missing_is_zero=True,
            ),
        ),
    )

    assert all(result.passed for result in results)


def test_missing_required_span_reports_unavailable_current_value() -> None:
    results = check_view_hints(
        current=_payload(),
        baseline=_payload(
            span_ms={("large_reply_first_press", "agents.view_files"): 30.0}
        ),
        span_gates=(
            SpanGate(
                "large",
                step="large_reply_first_press",
                span="agents.view_files",
            ),
        ),
        counter_gates=(),
    )

    assert not results[0].passed
    assert "current value unavailable" in results[0].failures
