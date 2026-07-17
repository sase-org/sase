"""Tests for local telemetry store status."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.telemetry.cli_status import (
    build_telemetry_status_payload,
    handle_telemetry_status,
)
from tests.telemetry.conftest import record_samples, use_store


def test_status_disabled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    use_store(tmp_path / "metrics.sqlite", enabled=False)

    handle_telemetry_status()

    output = capsys.readouterr().out
    assert "disabled" in output.lower()
    assert "sase.yml" in output


def test_status_reports_store_counts_and_freshness(tmp_path: Path) -> None:
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
                "value": 3,
            }
        ],
        now_ts=100,
    )

    with patch("sase.telemetry.cli_status.time.time", return_value=110):
        payload = build_telemetry_status_payload()

    assert payload["store"]["path"] == str(store_path)
    assert payload["store"]["sample_count"] == 1
    assert payload["store"]["db_size_bytes"] > 0
    assert payload["flusher"]["state"] == "healthy"
    assert payload["freshness"]["agent"]["age_seconds"] == 10
    assert set(payload) == {
        "enabled",
        "metric_count",
        "metric_kind_counts",
        "store",
        "flusher",
        "freshness",
        "store_error",
    }


def test_status_renders_local_details(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    record_samples(
        store_path,
        [
            {
                "ts": 100,
                "metric": "sase_bead_operations_total",
                "kind": "counter",
                "labels": {"operation": "show"},
                "source": "cli-1",
                "value": 1,
            }
        ],
        now_ts=100,
    )

    with patch("sase.telemetry.cli_status.time.time", return_value=110):
        handle_telemetry_status()

    output = capsys.readouterr().out
    assert "Store" in output
    assert "metrics.sqlite" in output
    assert "Flusher" in output
    assert "Subsystem Freshness" in output


def test_status_surfaces_store_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    use_store(tmp_path / "metrics.sqlite")
    with patch(
        "sase.telemetry.cli_status.store_stats", side_effect=RuntimeError("busy")
    ):
        handle_telemetry_status()

    assert "Unable to open the local telemetry store" in capsys.readouterr().out
