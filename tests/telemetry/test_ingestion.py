"""Tests for local accumulator draining and Rust-core ingestion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sase_core_rs import telemetry_query_instant

from sase.telemetry import flush_metrics, metrics as m
from sase.telemetry._accumulators import Counter, Histogram
from sase.telemetry._config import _RetentionConfig, _TelemetryConfig
from sase.telemetry._registry import init_telemetry


def _config(store_path: Path) -> _TelemetryConfig:
    return _TelemetryConfig(
        enabled=True,
        store_path=store_path,
        retention=_RetentionConfig(
            raw_seconds=10_000,
            rollup_5m_seconds=20_000,
            rollup_1h_seconds=30_000,
        ),
    )


def _instant(store_path: Path, metric: str, *, now_ts: int = 200) -> dict:
    return telemetry_query_instant(
        str(store_path),
        {"metric": metric, "group_by": [], "now_ts": now_ts},
        1_000,
    )


def test_counter_flushes_are_deltas_across_sources(tmp_path: Path) -> None:
    store_path = tmp_path / "telemetry" / "metrics.sqlite"
    cfg = _config(store_path)

    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()
        m.AGENT_SPAWNS.labels(llm_provider="codex", project="sase").inc(2)
        with patch("sase.telemetry._registry.time.time", return_value=100):
            assert flush_metrics("agent-runner", {"instance": "one"}) == 1

        m.AGENT_SPAWNS.labels(llm_provider="codex", project="sase").inc(3)
        with patch("sase.telemetry._registry.time.time", return_value=110):
            assert flush_metrics("agent-runner", {"instance": "two"}) == 1

    result = _instant(store_path, "sase_agent_spawns_total")
    assert result["values"][0]["value"] == 5


def test_gauges_flush_last_value_for_each_source(tmp_path: Path) -> None:
    store_path = tmp_path / "metrics.sqlite"
    cfg = _config(store_path)

    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()
        m.AGENT_ACTIVE.labels(llm_provider="codex", project="sase").set(2)
        with patch("sase.telemetry._registry.time.time", return_value=100):
            flush_metrics("runner", {"instance": "one"})

        m.AGENT_ACTIVE.labels(llm_provider="codex", project="sase").set(3)
        with patch("sase.telemetry._registry.time.time", return_value=101):
            flush_metrics("runner", {"instance": "two"})

    result = _instant(store_path, "sase_agent_active", now_ts=101)
    assert result["values"][0]["value"] == 5


def test_histogram_flush_contains_delta_aggregates(tmp_path: Path) -> None:
    store_path = tmp_path / "metrics.sqlite"
    cfg = _config(store_path)

    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()
        duration = m.AGENT_RUN_DURATION.labels(llm_provider="codex", workflow="run")
        duration.observe(10)
        duration.observe(40)
        with patch("sase.telemetry._registry.time.time", return_value=100):
            flush_metrics("runner")

    result = _instant(store_path, "sase_agent_run_duration_seconds")
    value = result["values"][0]
    assert value["count"] == 2
    assert value["sum"] == 50
    assert value["min"] == 10
    assert value["max"] == 40
    assert value["buckets"][0] == {"le": 10.0, "count": 1}


def test_flush_failures_retry_then_drop_without_raising(tmp_path: Path) -> None:
    cfg = _config(tmp_path / "metrics.sqlite")
    with (
        patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg),
        patch(
            "sase_core_rs.telemetry_record_batch", side_effect=RuntimeError("busy")
        ) as record,
        patch("sase.telemetry._registry.time.sleep") as sleep,
    ):
        init_telemetry()
        m.AXE_CYCLES.labels(cycle_type="tick").inc()
        assert flush_metrics("axe") == 0
        assert record.call_count == 3
        assert sleep.call_count == 2

        # Counter deltas were intentionally dropped after bounded retries.
        assert flush_metrics("axe") == 0
        assert record.call_count == 3


def test_accumulators_validate_labels_and_counter_monotonicity() -> None:
    counter = Counter("sase_test_total", "test", ["provider"])
    with pytest.raises(ValueError, match="missing"):
        counter.labels()
    with pytest.raises(ValueError, match="unexpected"):
        counter.labels(provider="codex", extra="x")
    with pytest.raises(ValueError, match="non-negative"):
        counter.labels(provider="codex").inc(-1)


def test_histogram_bucket_deltas_are_cumulative() -> None:
    histogram = Histogram("sase_test_seconds", "test", [], buckets=[1.0, 5.0, 10.0])
    histogram.observe(0.5)
    histogram.observe(7.0)

    sample = histogram.drain(ts=100, source="test:pid=1")[0]
    assert sample["count"] == 2
    assert sample["sum"] == 7.5
    assert sample["buckets"] == [
        {"le": 1.0, "count": 1},
        {"le": 5.0, "count": 1},
        {"le": 10.0, "count": 2},
    ]
    assert histogram.drain(ts=101, source="test:pid=1") == []
