"""Tests for one-hour local telemetry health assessment."""

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.telemetry._config import HealthThresholds
from sase.telemetry.cli_health import (
    CRITICAL,
    OK,
    WARN,
    _HealthWindow,
    _SubsystemHealth,
    _assess_health,
    _overall_status,
    build_telemetry_health_payload,
    handle_telemetry_health,
)
from tests.telemetry.conftest import record_samples, use_store


def test_health_assesses_error_latency_and_retry_thresholds() -> None:
    window = _HealthWindow(
        sample_count=4,
        agent_total=100,
        agent_errors=5,
        agent_p95=650,
        llm_total=100,
        llm_errors=1,
        llm_retries=15,
    )

    results = _assess_health(window, HealthThresholds())

    agents = next(result for result in results if result.name == "Agents")
    llm = next(result for result in results if result.name == "LLM")
    assert agents.status == CRITICAL
    assert "p95 650s" in agents.detail
    assert llm.status == WARN
    assert "retry rate 15.0%" in llm.detail


def test_health_informational_subsystems() -> None:
    window = _HealthWindow(
        sample_count=5,
        input_tokens=5000,
        output_tokens=2000,
        bead_active=2,
        bead_operations=10,
        vcs_operations=3,
        notifications_sent=4,
    )

    results = _assess_health(window, HealthThresholds())

    assert {result.name for result in results} == {
        "LLM Tokens",
        "Beads",
        "VCS",
        "Notifications",
    }
    assert all(result.status == OK for result in results)


def test_overall_status_uses_worst_result() -> None:
    assert _overall_status([]) == OK
    assert _overall_status([_SubsystemHealth("A", WARN, "")]) == WARN
    assert (
        _overall_status(
            [_SubsystemHealth("A", WARN, ""), _SubsystemHealth("B", CRITICAL, "")]
        )
        == CRITICAL
    )


def test_health_payload_queries_real_local_store(tmp_path: Path) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    record_samples(
        store_path,
        [
            {
                "ts": 100,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"status": "ok"},
                "source": "runner-1",
                "value": 9,
            },
            {
                "ts": 100,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"status": "error"},
                "source": "runner-1",
                "value": 1,
            },
            {
                "ts": 100,
                "metric": "sase_agent_run_duration_seconds",
                "kind": "histogram",
                "labels": {},
                "source": "runner-1",
                "count": 2,
                "sum": 50,
                "min": 10,
                "max": 40,
                "buckets": [{"le": 10, "count": 1}, {"le": 60, "count": 2}],
            },
        ],
        now_ts=120,
    )

    with patch("sase.telemetry.cli_health.time.time", return_value=120):
        payload = build_telemetry_health_payload()

    assert payload["source"] == "local"
    assert payload["sample_count"] > 0
    assert payload["status"] == "warn"
    assert payload["subsystems"][0]["name"] == "Agents"


def test_health_payload_empty_store(tmp_path: Path) -> None:
    use_store(tmp_path / "metrics.sqlite")

    with patch("sase.telemetry.cli_health.time.time", return_value=120):
        payload = build_telemetry_health_payload()

    assert payload["status"] == "no_data"
    assert payload["subsystems"] == []


def test_health_handler_preserves_exit_codes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch(
        "sase.telemetry.cli_health.build_telemetry_health_payload",
        return_value={
            "status": "warn",
            "subsystems": [
                {"name": "Agents", "status": "warn", "detail": "error rate 12%"}
            ],
        },
    ):
        with pytest.raises(SystemExit, match="1"):
            handle_telemetry_health(Namespace(json=False))

    assert "DEGRADED" in capsys.readouterr().out


def test_health_handler_no_data_is_critical(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch(
        "sase.telemetry.cli_health.build_telemetry_health_payload",
        return_value={"status": "no_data", "subsystems": []},
    ):
        with pytest.raises(SystemExit, match="2"):
            handle_telemetry_health(Namespace(json=False))

    assert "No telemetry samples" in capsys.readouterr().out
