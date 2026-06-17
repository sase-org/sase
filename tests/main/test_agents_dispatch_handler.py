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
from sase.main.parser import create_parser


def test_dispatch_bare_defaults_to_list() -> None:
    """A bare `sase agents` (no subcommand) invokes the list handler."""
    args = argparse.Namespace(
        agents_subcommand=None, all=False, json=True, project=None
    )
    with (
        patch("sase.agents.cli_list.list_running_agents", return_value=[]),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 0


def test_dispatch_list_subcommand() -> None:
    """`sase agents list` dispatches to the running-agents list handler."""
    args = argparse.Namespace(
        agents_subcommand="list", all=False, json=True, project=None
    )
    with (
        patch("sase.agents.cli_list.list_running_agents", return_value=[]),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 0


def test_parser_bare_agents_defaults_to_list() -> None:
    """Bare `sase agents` resolves to the `list` subcommand via list-default."""
    args = create_parser().parse_args(["agents"])

    assert args.command == "agents"
    assert args.agents_subcommand == "list"


def test_parser_registers_list_flags() -> None:
    """`sase agents list` accepts the `-a/-j/-p` listing flags."""
    args = create_parser().parse_args(["agents", "list", "-a", "-j", "-p", "proj"])

    assert args.command == "agents"
    assert args.agents_subcommand == "list"
    assert args.all is True
    assert args.json is True
    assert args.project == "proj"


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


def test_parser_registers_index_gc_options() -> None:
    """`sase agents index gc` accepts the shared index path knobs."""
    args = create_parser().parse_args(
        [
            "agents",
            "index",
            "gc",
            "--index-path",
            "/tmp/index.sqlite",
            "--projects-root",
            "/tmp/projects",
            "--json",
        ]
    )

    assert args.command == "agents"
    assert args.agents_subcommand == "index"
    assert args.index_subcommand == "gc"
    assert args.index_path == "/tmp/index.sqlite"
    assert args.projects_root == "/tmp/projects"
    assert args.json is True


def test_parser_registers_artifacts_layout_migrate_options() -> None:
    """`sase agents artifacts layout migrate` accepts migration knobs."""
    args = create_parser().parse_args(
        [
            "agents",
            "artifacts",
            "layout",
            "migrate",
            "--dry-run",
            "--manifest",
            "/tmp/manifest.json",
            "--projects-root",
            "/tmp/projects",
            "--index-path",
            "/tmp/index.sqlite",
            "--project",
            "proj",
            "--json",
        ]
    )

    assert args.command == "agents"
    assert args.agents_subcommand == "artifacts"
    assert args.artifacts_subcommand == "layout"
    assert args.layout_subcommand == "migrate"
    assert args.dry_run is True
    assert args.manifest == "/tmp/manifest.json"
    assert args.projects_root == "/tmp/projects"
    assert args.index_path == "/tmp/index.sqlite"
    assert args.project == "proj"
    assert args.json is True


def test_parser_rejects_artifacts_layout_migrate_force() -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(
            [
                "agents",
                "artifacts",
                "layout",
                "migrate",
                "--force",
            ]
        )


def test_dispatch_artifacts_layout_status_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sase agents artifacts layout status -j` dispatches to the layout handler."""
    args = argparse.Namespace(
        agents_subcommand="artifacts",
        artifacts_subcommand="layout",
        layout_subcommand="status",
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        project="proj",
        json=True,
    )

    with (
        patch(
            "sase.agents.cli_artifacts_layout.iter_agent_artifact_dirs", return_value=[]
        ),
        patch(
            "sase.agents.cli_artifacts_layout.agent_artifact_index_status",
            side_effect=FileNotFoundError("missing"),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["flat_dirs"] == 0
    assert payload["index_error"] == "missing"


def test_dispatch_index_gc_json(capsys: pytest.CaptureFixture[str]) -> None:
    """`sase agents index gc -j` reports reconciliation diagnostics."""
    args = argparse.Namespace(
        agents_subcommand="index",
        index_subcommand="gc",
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
                indexed_rows=3,
                source_rows=4,
                stale_rows=2,
                missing_rows=1,
                extra_rows=1,
                corrupt_rows=0,
            ),
        ) as mock_verify,
        patch(
            "sase.agents.cli_index.rebuild_agent_artifact_index",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                rows_indexed=4,
                rows_deleted=0,
                rows_skipped=0,
            ),
        ) as mock_rebuild,
        patch(
            "sase.agents.cli_index._load_dismissed_identities_for_gc",
            return_value=([], 2),
        ),
        patch(
            "sase.agents.cli_index.replace_agent_artifact_index_dismissed_agents",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="",
                rows_indexed=5,
                rows_deleted=3,
                rows_skipped=0,
            ),
        ) as mock_hide,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)

    assert excinfo.value.code == 0
    mock_verify.assert_called_once()
    mock_rebuild.assert_called_once()
    mock_hide.assert_called_once()
    payload = json.loads(capsys.readouterr().out)
    assert payload["index_path"] == "/tmp/index.sqlite"
    assert payload["rows_indexed"] == 4
    assert payload["rows_deleted"] == 1
    assert payload["rows_hidden"] == 5
    assert payload["rows_skipped"] == 2
    assert payload["stale_rows_rewritten"] == 2


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
