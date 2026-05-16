"""Tests for `sase agents` dispatch, archive, and index commands."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.core.agent_scan_wire import (
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVerifyWire,
)
from sase.main.agents_handler import handle_agents_command


def test_dispatch_bare_defaults_to_status() -> None:
    """A bare `sase agents` (no subcommand) invokes the status handler."""
    args = argparse.Namespace(
        agents_subcommand=None, all=False, json=True, project=None
    )
    with (
        patch("sase.agents.cli_status.list_running_agents", return_value=[]),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 0


def test_dispatch_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown subcommand prints usage and exits 1."""
    args = argparse.Namespace(agents_subcommand="bogus")
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_command(args)
    assert excinfo.value.code == 1
    assert "Usage: sase agents" in capsys.readouterr().out


def test_dispatch_archive_rebuild_index(capsys: pytest.CaptureFixture[str]) -> None:
    """Archive maintenance dispatches to the dismissed-bundle index rebuild."""
    args = argparse.Namespace(
        agents_subcommand="archive",
        archive_subcommand="rebuild-index",
    )
    with (
        patch(
            "sase.ace.dismissed_agents.rebuild_dismissed_bundle_index",
            return_value=(2, 1),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 0
    assert (
        "Indexed 2 dismissed bundles; skipped 1 corrupt files."
        in capsys.readouterr().out
    )


def test_dispatch_archive_verify_exits_nonzero_when_stale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Archive verify reports failures through its process exit code."""
    args = argparse.Namespace(
        agents_subcommand="archive",
        archive_subcommand="verify",
    )
    with (
        patch(
            "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
            return_value={
                "ok": False,
                "indexed_rows": 1,
                "valid_bundles": 2,
                "corrupt_bundles": 0,
                "stale_rows": 0,
                "missing_rows": 1,
            },
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 1
    assert '"missing_rows": 1' in capsys.readouterr().out


def test_dispatch_index_rebuild_json(capsys: pytest.CaptureFixture[str]) -> None:
    """`sase agents index rebuild -j` reports the Rust rebuild summary."""
    args = argparse.Namespace(
        agents_subcommand="index",
        index_subcommand="rebuild",
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        json=True,
    )
    update = {
        "schema_version": 1,
        "index_path": "/tmp/index.sqlite",
        "projects_root": "/tmp/projects",
        "rows_indexed": 7,
        "rows_deleted": 0,
        "rows_skipped": 0,
    }

    with (
        patch(
            "sase.agents.cli_index.rebuild_agent_artifact_index",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                rows_indexed=7,
                rows_deleted=0,
                rows_skipped=0,
            ),
        ) as mock_rebuild,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)

    assert excinfo.value.code == 0
    mock_rebuild.assert_called_once()
    assert json.loads(capsys.readouterr().out) == update


def test_dispatch_index_verify_json_exits_nonzero_when_stale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sase agents index verify -j` reports drift and exits nonzero."""
    args = argparse.Namespace(
        agents_subcommand="index",
        index_subcommand="verify",
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        json=True,
    )

    with (
        patch(
            "sase.agents.cli_index.verify_agent_artifact_index",
            return_value=AgentArtifactIndexVerifyWire(
                ok=False,
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                indexed_rows=1,
                source_rows=2,
                missing_rows=1,
            ),
        ) as mock_verify,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)

    assert excinfo.value.code == 1
    mock_verify.assert_called_once()
    assert json.loads(capsys.readouterr().out)["missing_rows"] == 1


def test_dispatch_index_diagnose_json_exits_nonzero_when_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sase agents index diagnose -j` reports pattern-specific gaps."""
    args = argparse.Namespace(
        agents_subcommand="index",
        index_subcommand="diagnose",
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        pattern="sase-3r",
        json=True,
    )

    with (
        patch(
            "sase.agents.cli_index.diagnose_agent_artifact_index_timestamps",
            return_value={
                "ok": False,
                "pattern": "sase-3r",
                "missing_timestamps": ["20260516095502"],
            },
        ) as mock_diagnose,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)

    assert excinfo.value.code == 1
    mock_diagnose.assert_called_once()
    assert json.loads(capsys.readouterr().out)["missing_timestamps"] == [
        "20260516095502"
    ]
