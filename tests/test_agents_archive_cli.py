"""CLI coverage for dismissed-agent archive maintenance commands."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.agents.cli_archive import handle_agents_archive


def _archive_args(subcommand: str) -> argparse.Namespace:
    return argparse.Namespace(archive_subcommand=subcommand)


def test_archive_rebuild_index_reports_indexed_and_skipped_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "sase.ace.dismissed_agents.rebuild_dismissed_bundle_index",
            return_value=(3, 2),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(_archive_args("rebuild-index"))

    assert excinfo.value.code == 0
    assert (
        "Indexed 3 dismissed bundles; skipped 2 corrupt files."
        in capsys.readouterr().out
    )


def test_archive_verify_emits_json_and_exits_zero_when_index_is_clean(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "ok": True,
        "indexed_rows": 2,
        "valid_bundles": 2,
        "corrupt_bundles": 0,
        "stale_rows": 0,
        "missing_rows": 0,
    }
    with (
        patch(
            "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
            return_value=result,
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(_archive_args("verify"))

    assert excinfo.value.code == 0
    assert json.loads(capsys.readouterr().out) == result


def test_archive_verify_exits_nonzero_when_index_has_drift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "ok": False,
        "indexed_rows": 1,
        "valid_bundles": 2,
        "corrupt_bundles": 0,
        "stale_rows": 0,
        "missing_rows": 1,
    }
    with (
        patch(
            "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
            return_value=result,
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(_archive_args("verify"))

    assert excinfo.value.code == 1
    assert json.loads(capsys.readouterr().out) == result


def test_archive_unknown_subcommand_prints_maintenance_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_archive(_archive_args("search"))

    assert excinfo.value.code == 1
    assert "Usage: sase agent archive {rebuild-index,verify}" in capsys.readouterr().out
