"""Tests for `sase agent` dispatch, archive, and index commands."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.core.agent_scan_wire import (
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVerifyWire,
)
from sase.main.agent_handler import handle_agent_command
from sase.main.parser import create_parser


def test_dispatch_bare_defaults_to_list() -> None:
    """A bare `sase agent` (no subcommand) invokes the list handler."""
    args = argparse.Namespace(agent_subcommand=None, all=False, json=True, project=None)
    with (
        patch("sase.agents.cli_list.agent_list_entries", return_value=[]),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)
    assert excinfo.value.code == 0


def test_dispatch_list_subcommand() -> None:
    """`sase agent list` dispatches to the running-agents list handler."""
    args = argparse.Namespace(
        agent_subcommand="list", all=False, json=True, project=None
    )
    with (
        patch("sase.agents.cli_list.agent_list_entries", return_value=[]),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)
    assert excinfo.value.code == 0


def test_parser_bare_agents_defaults_to_list() -> None:
    """Bare `sase agent` resolves to the `list` subcommand via list-default."""
    args = create_parser().parse_args(["agent"])

    assert args.command == "agent"
    assert args.agent_subcommand == "list"


def test_parser_registers_list_flags() -> None:
    """`sase agent list` accepts the `-a/-j/-p` listing flags."""
    args = create_parser().parse_args(["agent", "list", "-a", "-j", "-p", "proj"])

    assert args.command == "agent"
    assert args.agent_subcommand == "list"
    assert args.all is True
    assert args.json is True
    assert args.project == "proj"


def test_dispatch_restart() -> None:
    """``sase agent restart`` dispatches to the restart handler."""
    args = argparse.Namespace(
        agent_subcommand="restart",
        name="02p",
        json=False,
        dry_run=True,
        yes=False,
        model=None,
    )
    with (
        patch("sase.agents.cli_restart.handle_agents_restart", return_value=0),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)
    assert excinfo.value.code == 0


def test_dispatch_drain() -> None:
    """``sase agent drain`` dispatches through the operation handler."""
    args = argparse.Namespace(
        agent_subcommand="drain",
        provider="claude",
        json=True,
        dry_run=True,
        yes=False,
        model=None,
        limit=20,
    )
    with (
        patch("sase.ops.commands.agent.handle_agent_operation", return_value=0),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)
    assert excinfo.value.code == 0


def test_dispatch_wait() -> None:
    """``sase agent wait`` dispatches to the wait handler."""
    args = argparse.Namespace(agent_subcommand="wait", names=["02p"])
    with (
        patch("sase.agents.cli_wait.handle_agents_wait", return_value=3),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)
    assert excinfo.value.code == 3


def test_parser_registers_wait_options() -> None:
    """``sase agent wait`` accepts the documented option table and NAME positional."""
    args = create_parser().parse_args(
        [
            "agent",
            "wait",
            "-i",
            "5s",
            "-p",
            "proj",
            "-t",
            "2h",
            "-w",
            "foo",
            "bar",
        ]
    )

    assert args.command == "agent"
    assert args.agent_subcommand == "wait"
    assert args.all is False
    assert args.interval == "5s"
    assert args.json is False
    assert args.project == "proj"
    assert args.quiet is False
    assert args.timeout == "2h"
    assert args.wait_blocked is True
    assert args.names == ["foo", "bar"]


def test_parser_rejects_wait_all_and_name_together_is_a_runtime_check() -> None:
    """Argparse itself accepts ``-a`` with NAME; the handler rejects it at runtime."""
    args = create_parser().parse_args(["agent", "wait", "-a", "foo"])

    assert args.all is True
    assert args.names == ["foo"]


def test_dispatch_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown subcommand prints usage and exits 1."""
    args = argparse.Namespace(agent_subcommand="bogus")
    with pytest.raises(SystemExit) as excinfo:
        handle_agent_command(args)
    assert excinfo.value.code == 1
    assert "Usage: sase agent" in capsys.readouterr().out


def test_dispatch_archive_rebuild_index(capsys: pytest.CaptureFixture[str]) -> None:
    """Archive maintenance dispatches to the dismissed-bundle index rebuild."""
    args = argparse.Namespace(
        agent_subcommand="archive",
        archive_subcommand="rebuild-index",
    )
    with (
        patch(
            "sase.ace.dismissed_agents.rebuild_dismissed_bundle_index",
            return_value=(2, 1),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)
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
        agent_subcommand="archive",
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
        handle_agent_command(args)
    assert excinfo.value.code == 1
    assert '"missing_rows": 1' in capsys.readouterr().out


def test_dispatch_index_rebuild_json(capsys: pytest.CaptureFixture[str]) -> None:
    """`sase agent index rebuild -j` reports the Rust rebuild summary."""
    args = argparse.Namespace(
        agent_subcommand="index",
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
        "hidden_terminal_rows_retained": 0,
        "hidden_terminal_rows_pruned": 0,
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
        handle_agent_command(args)

    assert excinfo.value.code == 0
    mock_rebuild.assert_called_once()
    assert json.loads(capsys.readouterr().out) == update


def test_parser_registers_index_gc_options() -> None:
    """`sase agent index gc` accepts the shared index path knobs."""
    args = create_parser().parse_args(
        [
            "agent",
            "index",
            "gc",
            "--index-path",
            "/tmp/index.sqlite",
            "--projects-root",
            "/tmp/projects",
            "--json",
        ]
    )

    assert args.command == "agent"
    assert args.agent_subcommand == "index"
    assert args.index_subcommand == "gc"
    assert args.index_path == "/tmp/index.sqlite"
    assert args.projects_root == "/tmp/projects"
    assert args.json is True


def test_parser_registers_index_repair_as_dry_run_by_default() -> None:
    args = create_parser().parse_args(
        [
            "agent",
            "index",
            "repair",
            "--index-path",
            "/tmp/index.sqlite",
            "--projects-root",
            "/tmp/projects",
            "--json",
        ]
    )

    assert args.index_subcommand == "repair"
    assert args.apply is False
    assert args.index_path == "/tmp/index.sqlite"
    assert args.projects_root == "/tmp/projects"
    assert args.json is True

    applied = create_parser().parse_args(["agent", "index", "repair", "--apply"])
    assert applied.apply is True


def test_parser_registers_index_vacuum_as_dry_run_by_default() -> None:
    args = create_parser().parse_args(
        [
            "agent",
            "index",
            "vacuum",
            "--index-path",
            "/tmp/index.sqlite",
            "--json",
        ]
    )

    assert args.command == "agent"
    assert args.agent_subcommand == "index"
    assert args.index_subcommand == "vacuum"
    assert args.apply is False
    assert args.index_path == "/tmp/index.sqlite"
    assert args.json is True

    applied = create_parser().parse_args(["agent", "index", "vacuum", "--apply"])
    assert applied.apply is True


def test_parser_registers_artifacts_layout_migrate_options() -> None:
    """`sase agent artifacts layout migrate` accepts migration knobs."""
    args = create_parser().parse_args(
        [
            "agent",
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

    assert args.command == "agent"
    assert args.agent_subcommand == "artifacts"
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
                "agent",
                "artifacts",
                "layout",
                "migrate",
                "--force",
            ]
        )


def test_dispatch_artifacts_layout_status_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sase agent artifacts layout status -j` dispatches to the layout handler."""
    args = argparse.Namespace(
        agent_subcommand="artifacts",
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
        handle_agent_command(args)

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["flat_dirs"] == 0
    assert payload["index_error"] == "missing"


def test_dispatch_index_gc_json(capsys: pytest.CaptureFixture[str]) -> None:
    """`sase agent index gc -j` reports reconciliation diagnostics."""
    args = argparse.Namespace(
        agent_subcommand="index",
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
        patch(
            "sase.agents.cli_index.prune_hidden_terminal_agent_artifact_index_rows",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="",
                hidden_terminal_rows_retained=4096,
                hidden_terminal_rows_pruned=7,
            ),
        ) as mock_prune,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agent_command(args)

    assert excinfo.value.code == 0
    mock_verify.assert_called_once()
    mock_rebuild.assert_called_once()
    mock_hide.assert_called_once()
    mock_prune.assert_called_once()
    payload = json.loads(capsys.readouterr().out)
    assert payload["index_path"] == "/tmp/index.sqlite"
    assert payload["rows_indexed"] == 4
    assert payload["rows_deleted"] == 1
    assert payload["rows_hidden"] == 5
    assert payload["rows_skipped"] == 2
    assert payload["stale_rows_rewritten"] == 2
    assert payload["hidden_terminal_rows_pruned"] == 7


def test_dispatch_index_verify_json_exits_nonzero_when_stale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sase agent index verify -j` reports drift and exits nonzero."""
    args = argparse.Namespace(
        agent_subcommand="index",
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
        handle_agent_command(args)

    assert excinfo.value.code == 1
    mock_verify.assert_called_once()
    assert json.loads(capsys.readouterr().out)["missing_rows"] == 1
