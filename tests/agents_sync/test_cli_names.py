from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.agents.cli_sync import handle_agents_sync
from sase.agents.cli_names import handle_agents_names
from sase.agents_sync.purge_local_state import PurgeLocalStateOutcome
from sase.main.parser import create_parser


def test_names_bare_usage_lists_both_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(names_subcommand=None)
    with pytest.raises(SystemExit) as exc_info:
        handle_agents_names(args)

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "migrate-auto" in output
    assert "purge-local-state" in output


def test_names_purge_local_state_parser_accepts_apply_and_json() -> None:
    dry_run = create_parser().parse_args(["agent", "names", "purge-local-state"])
    apply = create_parser().parse_args(
        ["agent", "names", "purge-local-state", "--json", "--apply"]
    )

    assert dry_run.names_subcommand == "purge-local-state"
    assert dry_run.apply is False
    assert apply.apply and apply.json


def test_names_purge_local_state_cli_dispatches_and_reports_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcome = PurgeLocalStateOutcome(True)
    args = argparse.Namespace(
        names_subcommand="purge-local-state",
        apply=False,
        json=True,
    )
    with patch(
        "sase.agents_sync.purge_local_state.purge_local_import_state",
        return_value=outcome,
    ):
        with pytest.raises(SystemExit) as exc_info:
            handle_agents_names(args)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run"
    assert payload["artifact_dirs"] == []


def test_parser_accepts_repair_states_flags() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "-s", "-p", "one", "-L", "25", "-A", "cursor-1", "-j"]
    )

    assert args.repair_states
    assert args.project == ["one"]
    assert args.state_limit == 25
    assert args.state_after == "cursor-1"


def test_parser_rejects_repair_states_combinations() -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--repair-states"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(
            ["agent", "sync", "--repair-states", "-p", "one", "--check"]
        )
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(
            ["agent", "sync", "--repair-states", "-p", "one", "--repair-revisions"]
        )
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "-L", "5", "-p", "one"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--apply", "-p", "one"])
    assert exc_info.value.code == 2


def test_repair_states_dispatches_and_reports_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agents_sync.publication_state_repair import StateRepairReport

    reports = (
        StateRepairReport(
            "proj",
            "Project",
            "preview",
            examined=2,
            changed=1,
            next_cursor="cursor-1",
        ),
    )
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        repair_states=True,
        apply=False,
        state_limit=100,
        state_after=None,
    )
    with patch(
        "sase.agents.cli_sync.repair_agent_run_states", return_value=reports
    ) as repair:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repair-states"
    assert payload["projects"][0]["examined"] == 2
    assert payload["projects"][0]["next_cursor"] == "cursor-1"
    assert exit_code == 0
    repair.assert_called_once_with(
        ("proj",), apply=False, state_limit=100, state_after=None
    )
