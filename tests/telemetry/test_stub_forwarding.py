"""Regression tests: stubs must forward to real metrics after init_telemetry().

Context: modules often import metrics at module load via
``from sase.telemetry.metrics import AGENT_RUNS``. Before the stub-forwarding
fix, ``init_telemetry()`` replaced the module attribute only, so pre-init
imports kept a dead stub binding and all ``.labels().inc()`` calls silently
no-opped. These tests pin the new contract: both pre-init and post-init
imports end up incrementing the same real metric.
"""

from __future__ import annotations

from sase.telemetry import metrics as m
from tests.telemetry.conftest import init_enabled, sample


def test_pre_init_import_still_counts() -> None:
    """Binding grabbed before init_telemetry() must still reach the registry."""
    pre_init_agent_runs = m.AGENT_RUNS  # simulates `from ... import AGENT_RUNS`

    reg = init_enabled()

    pre_init_agent_runs.labels(llm_provider="claude", status="ok", workflow="run").inc()

    value = sample(
        reg,
        "sase_agent_runs_total",
        {"llm_provider": "claude", "status": "ok", "workflow": "run"},
    )
    assert value == 1.0


def test_post_init_import_still_counts() -> None:
    """Binding grabbed after init_telemetry() is the real metric directly."""
    reg = init_enabled()

    post_init_agent_runs = m.AGENT_RUNS

    post_init_agent_runs.labels(
        llm_provider="gemini", status="ok", workflow="run"
    ).inc()

    value = sample(
        reg,
        "sase_agent_runs_total",
        {"llm_provider": "gemini", "status": "ok", "workflow": "run"},
    )
    assert value == 1.0


def test_pre_and_post_init_bindings_share_counter() -> None:
    """Both import paths must target the same real metric — no double-count, no split."""
    pre_init_agent_runs = m.AGENT_RUNS

    reg = init_enabled()

    post_init_agent_runs = m.AGENT_RUNS

    pre_init_agent_runs.labels(llm_provider="claude", status="ok", workflow="run").inc()
    post_init_agent_runs.labels(
        llm_provider="claude", status="ok", workflow="run"
    ).inc()

    value = sample(
        reg,
        "sase_agent_runs_total",
        {"llm_provider": "claude", "status": "ok", "workflow": "run"},
    )
    assert value == 2.0


def test_pre_init_gauge_inc_dec_forwards() -> None:
    """Gauges exercise inc/dec/set through the stub as well."""
    pre_init_agent_active = m.AGENT_ACTIVE

    reg = init_enabled()

    pre_init_agent_active.labels(llm_provider="claude", project="p").inc()
    pre_init_agent_active.labels(llm_provider="claude", project="p").inc()
    pre_init_agent_active.labels(llm_provider="claude", project="p").dec()

    value = sample(reg, "sase_agent_active", {"llm_provider": "claude", "project": "p"})
    assert value == 1.0


def test_pre_init_histogram_observe_forwards() -> None:
    """Histograms forward observe() through the stub."""
    pre_init_duration = m.AGENT_RUN_DURATION

    reg = init_enabled()

    pre_init_duration.labels(llm_provider="claude", workflow="run").observe(12.0)

    count = sample(
        reg,
        "sase_agent_run_duration_seconds_count",
        {"llm_provider": "claude", "workflow": "run"},
    )
    assert count == 1.0
