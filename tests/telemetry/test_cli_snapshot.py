"""Tests for ``sase telemetry snapshot`` local-store queries."""

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.telemetry.cli_snapshot import handle_telemetry_snapshot
from tests.telemetry.conftest import record_samples, use_store


def _seed_snapshot(store_path: Path) -> None:
    record_samples(
        store_path,
        [
            {
                "ts": 100,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"llm_provider": "codex", "status": "ok", "workflow": ""},
                "source": "runner-1",
                "value": 42,
            },
            {
                "ts": 105,
                "metric": "sase_agent_active",
                "kind": "gauge",
                "labels": {"llm_provider": "codex", "project": "sase"},
                "source": "axe-1",
                "value": 2,
            },
            {
                "ts": 100,
                "metric": "sase_vcs_operations_total",
                "kind": "counter",
                "labels": {
                    "provider": "git",
                    "operation": "commit",
                    "status": "ok",
                },
                "source": "cli-1",
                "value": 5,
            },
        ],
        now_ts=110,
    )


def _run_snapshot(
    store_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    fmt: str = "rich",
    subsystem: str | None = None,
) -> str:
    use_store(store_path)
    with patch("sase.telemetry.cli_snapshot.time.time", return_value=110):
        handle_telemetry_snapshot(Namespace(format=fmt, subsystem=subsystem))
    return capsys.readouterr().out


def test_snapshot_rich_groups_local_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    _seed_snapshot(store_path)

    output = _run_snapshot(store_path, capsys)

    assert "Agent Lifecycle" in output
    assert "VCS / Workspace" in output
    assert "sase_agent_runs_total" in output
    assert "codex" in output
    assert "42" in output


def test_snapshot_subsystem_filter_is_case_insensitive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    _seed_snapshot(store_path)

    output = _run_snapshot(store_path, capsys, subsystem="vcs / workspace")

    assert "VCS / Workspace" in output
    assert "sase_vcs_operations_total" in output
    assert "Agent Lifecycle" not in output


def test_snapshot_json_has_store_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    _seed_snapshot(store_path)

    output = _run_snapshot(store_path, capsys, fmt="json")

    assert '"store_path"' in output
    assert '"samples"' in output
    assert '"sase_agent_runs_total"' in output


def test_snapshot_empty_store_is_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _run_snapshot(tmp_path / "metrics.sqlite", capsys)

    assert "No telemetry samples have been recorded yet" in output
