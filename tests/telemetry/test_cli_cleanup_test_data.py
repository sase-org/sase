"""Tests for explicit test-data telemetry maintenance."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.parser import create_parser
from sase.telemetry.cli_cleanup_test_data import (
    handle_telemetry_cleanup_test_data,
)
from sase.telemetry.maintenance import cleanup_test_data
from sase.telemetry.query import store_stats
from tests.main.parser_help_helpers import flat_help, parser_for
from tests.telemetry.conftest import record_samples, use_store


def _report(total: int = 3) -> dict[str, object]:
    return {
        "raw_rows": total,
        "rollup_5m_rows": 0,
        "rollup_1h_rows": 0,
        "total_rows": total,
        "store_size_before_bytes": 4096,
        "store_size_after_bytes": 4096,
        "reclaimed_bytes": 0,
    }


def test_cleanup_parser_help_and_short_aliases() -> None:
    help_text = flat_help(
        parser_for(("sase", "telemetry", "cleanup-test-data")).format_help()
    )
    args = create_parser().parse_args(["telemetry", "cleanup-test-data", "-n", "-y"])

    assert "-n, --dry-run" in help_text
    assert "-y, --yes" in help_text
    assert "exact labels" in help_text
    assert "sase telemetry cleanup-test-data --dry-run" in help_text
    assert args.dry_run is True
    assert args.yes is True


def test_cleanup_without_yes_previews_then_refuses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(dry_run=False, yes=False)
    with patch(
        "sase.telemetry.cli_cleanup_test_data.cleanup_test_data",
        return_value=_report(),
    ) as cleanup:
        with pytest.raises(SystemExit) as exc:
            handle_telemetry_cleanup_test_data(args)

    assert exc.value.code == 2
    cleanup.assert_called_once_with(dry_run=True)
    assert "Refusing deletion without explicit" in capsys.readouterr().out


def test_cleanup_dry_run_never_invokes_mutation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(dry_run=True, yes=False)
    with patch(
        "sase.telemetry.cli_cleanup_test_data.cleanup_test_data",
        return_value=_report(),
    ) as cleanup:
        handle_telemetry_cleanup_test_data(args)

    cleanup.assert_called_once_with(dry_run=True)
    assert "Dry run only" in capsys.readouterr().out


def test_cleanup_end_to_end_preserves_production_and_near_miss_rows(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    record_samples(
        store_path,
        [
            {
                "ts": 100,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"llm_provider": "test-provider"},
                "source": "test-provider",
                "value": 1,
            },
            {
                "ts": 101,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"llm_provider": "fakey"},
                "source": "fakey",
                "value": 1,
            },
            {
                "ts": 102,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"workflow": "test-workflow"},
                "source": "test-workflow",
                "value": 1,
            },
            {
                "ts": 103,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"llm_provider": "test-provider-near-miss"},
                "source": "production",
                "value": 7,
            },
        ],
        now_ts=103,
    )

    preview = cleanup_test_data(dry_run=True)
    assert preview["total_rows"] == 3
    assert store_stats()["raw_sample_count"] == 4

    deleted = cleanup_test_data(dry_run=False)
    assert deleted["total_rows"] == 3
    assert store_stats()["raw_sample_count"] == 1

    repeated = cleanup_test_data(dry_run=False)
    assert repeated["total_rows"] == 0
