"""Cross-cutting instrumentation tests: accumulation, label independence, etc."""

from __future__ import annotations

import pytest

from sase.telemetry import metrics as m
from tests.telemetry.conftest import init_disabled, init_enabled, sample


class TestCrossCutting:
    def test_counter_accumulates_across_multiple_inc(self) -> None:
        reg = init_enabled()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
        assert (
            sample(
                reg,
                "sase_agent_runs_total",
                {"llm_provider": "claude", "status": "ok", "workflow": ""},
            )
            == 3.0
        )

    def test_histogram_accumulates_observations(self) -> None:
        reg = init_enabled()
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.1)
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.2)
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.3)
        assert (
            sample(reg, "sase_axe_cycle_duration_seconds_count", {"cycle_type": "tick"})
            == 3.0
        )
        assert sample(
            reg, "sase_axe_cycle_duration_seconds_sum", {"cycle_type": "tick"}
        ) == pytest.approx(0.6)

    def test_distinct_label_values_tracked_independently(self) -> None:
        reg = init_enabled()
        m.LLM_INVOCATIONS.labels(provider="claude", status="ok").inc()
        m.LLM_INVOCATIONS.labels(provider="gemini", status="ok").inc()
        m.LLM_INVOCATIONS.labels(provider="claude", status="error").inc()
        assert (
            sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "ok"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "gemini", "status": "ok"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "error"},
            )
            == 1.0
        )

    def test_gauge_set_overwrites_previous(self) -> None:
        reg = init_enabled()
        m.BEAD_ACTIVE.labels(project="p", status="open").set(10)
        m.BEAD_ACTIVE.labels(project="p", status="open").set(7)
        assert (
            sample(reg, "sase_bead_active", {"project": "p", "status": "open"}) == 7.0
        )

    def test_histogram_time_context_manager(self) -> None:
        reg = init_enabled()
        with m.HOOK_DURATION.labels(hook_type="test").time():
            pass  # near-zero duration
        assert (
            sample(reg, "sase_hook_duration_seconds_count", {"hook_type": "test"})
            == 1.0
        )
        total = sample(reg, "sase_hook_duration_seconds_sum", {"hook_type": "test"})
        assert total is not None and total >= 0.0

    def test_all_metrics_recordable_after_init(self) -> None:
        """Every metric in METRIC_DEFS can be called after init without error."""
        from sase.telemetry.metrics import METRIC_DEFS

        init_enabled()
        for attr, kind, _, _, labelnames, _ in METRIC_DEFS:
            metric = getattr(m, attr)
            labels = dict.fromkeys(labelnames, "test")
            labeled = metric.labels(**labels) if labelnames else metric
            if kind == "counter":
                labeled.inc()
            elif kind == "gauge":
                labeled.set(1)
            elif kind == "histogram":
                labeled.observe(0.1)

    def test_all_stubs_callable_when_disabled(self) -> None:
        """Every metric in METRIC_DEFS can be called as a stub without error."""
        from sase.telemetry.metrics import METRIC_DEFS

        init_disabled()
        for attr, kind, _, _, labelnames, _ in METRIC_DEFS:
            metric = getattr(m, attr)
            labeled = (
                metric.labels(**dict.fromkeys(labelnames, "test"))
                if labelnames
                else metric
            )
            if kind == "counter":
                labeled.inc()
            elif kind == "gauge":
                labeled.set(1)
            elif kind == "histogram":
                labeled.observe(0.1)
