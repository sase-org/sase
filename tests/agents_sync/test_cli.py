from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.agents.cli_sync import handle_agents_sync
from sase.agents_sync.models import (
    ProjectSyncStatus,
    SyncOutcome,
    SyncStatusSnapshot,
)
from sase.main.parser import create_parser


def test_parser_accepts_repeatable_project_and_check_refresh() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "-c", "-r", "-p", "one", "-p", "two", "-j"]
    )

    assert args.agent_subcommand == "sync"
    assert args.check and args.refresh and args.json
    assert args.project == ["one", "two"]


def test_parser_rejects_refresh_without_check() -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--refresh"])

    assert exc_info.value.code == 2


def test_parser_accepts_retry_quarantined_only_for_full_sync() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "--retry-quarantined", "--project", "one"]
    )
    assert args.retry_quarantined

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--check", "--retry-quarantined"])
    assert exc_info.value.code == 2


def test_sync_help_distinguishes_full_cached_and_refresh_modes() -> None:
    parser = create_parser()
    root_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    agent_parser = root_action.choices["agent"]
    agent_action = next(
        action
        for action in agent_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    help_text = " ".join(agent_action.choices["sync"].format_help().split())

    assert "drain publication retries" in help_text
    assert "--check is local and network-free" in help_text
    assert "validate/cache incoming hoods without importing them" in help_text


def test_agent_help_keeps_bare_list_delegation_and_sorted_commands() -> None:
    parser = create_parser()
    agent_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    agent_parser = agent_action.choices["agent"]
    help_text = agent_parser.format_help()

    normalized_help = " ".join(help_text.split())
    assert "delegates to `sase agent list`" in normalized_help
    command_line = next(line for line in help_text.splitlines() if "archive" in line)
    assert command_line.index("archive") < command_line.index("artifacts")
    assert command_line.index("show") < command_line.index("sync")
    assert command_line.index("sync") < command_line.index("tribe")


def test_check_json_is_stable_and_errors_exit_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = SyncStatusSnapshot(
        10.0,
        (
            ProjectSyncStatus(
                "proj",
                "Project",
                "error",
                error="corrupt manifest",
            ),
        ),
    )
    args = argparse.Namespace(project=["proj"], check=True, refresh=False, json=True)
    with patch("sase.agents.cli_sync.get_agents_sync_status", return_value=snapshot):
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["mode"] == "check"
    assert payload["projects"][0]["error"] == "corrupt manifest"
    assert exit_code == 1


def test_mutating_sync_json_allows_benign_skips(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (SyncOutcome("proj", "Project", skip_reason="project is disabled"),)
    args = argparse.Namespace(project=[], check=False, refresh=False, json=True)
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes) as sync:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "sync"
    assert payload["projects"][0]["skip_reason"] == "project is disabled"
    assert exit_code == 0
    sync.assert_called_once_with((), retry_quarantined=False)


def test_mutating_sync_pretty_table_reports_counts_and_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            pulled=True,
            integrated=1,
            exported=2,
            committed=True,
            pushed=True,
        ),
    )
    args = argparse.Namespace(project=[], check=False, refresh=False, json=False)
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes):
        exit_code = handle_agents_sync(args)

    output = capsys.readouterr().out
    assert "Agent Sync" in output
    assert "Project" in output
    assert "synchronized" in output
    assert exit_code == 0
