from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.agents.cli_names import handle_agents_names
from sase.agents.cli_sync import handle_agents_sync
from sase.agents_sync.models import (
    STATUS_SCHEMA_VERSION,
    ProjectSyncStatus,
    SyncOutcome,
    SyncStatusSnapshot,
)
from sase.main.parser import create_parser
from sase.agents_sync.v1_forget_import import V1ForgetImportOutcome


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


def test_parser_accepts_repair_digests_flag() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "--repair-digests", "--project", "one"]
    )
    assert args.repair_digests
    assert args.project == ["one"]


def test_parser_accepts_repair_manifest_flag() -> None:
    args = create_parser().parse_args(
        ["agent", "sync", "--repair-manifest", "--project", "one"]
    )
    assert args.repair_manifest
    assert args.project == ["one"]


def test_parser_accepts_drop_retired_only_for_full_sync() -> None:
    args = create_parser().parse_args(["agent", "sync", "-d", "--project", "one"])
    assert args.drop_retired

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--check", "--drop-retired"])
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
    assert "computing ahead/behind" in help_text


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
    assert payload["schema_version"] == STATUS_SCHEMA_VERSION
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
    sync.assert_called_once_with((), retry_quarantined=False, drop_retired=False)


def test_mutating_sync_forwards_drop_retired_and_renders_its_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            pulled=True,
            diagnostics=(
                "dropped 1 retired publication request",
                "dropped retired publication request alice.athena.lt@bbbbbbbbbbbb: "
                "hood 'lt' has no publishable runs",
            ),
        ),
    )
    args = argparse.Namespace(
        project=[],
        check=False,
        refresh=False,
        json=False,
        drop_retired=True,
    )
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes) as sync:
        exit_code = handle_agents_sync(args)

    output = " ".join(capsys.readouterr().out.split())
    assert "dropped 1 retired publication request" in output
    assert "hood 'lt' has no publishable runs" in output
    assert exit_code == 0
    sync.assert_called_once_with((), retry_quarantined=False, drop_retired=True)


def test_mutating_sync_pretty_table_reports_counts_and_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            pulled=True,
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


def test_repair_digests_dispatches_before_check_and_reports_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            committed=True,
            pushed=True,
            diagnostics=("foo: agents/alice.athena.foo/chat.md",),
        ),
    )
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        repair_digests=True,
    )
    with patch(
        "sase.agents.cli_sync.repair_agent_hood_digests", return_value=outcomes
    ) as repair:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repair-digests"
    assert payload["projects"][0]["diagnostics"] == [
        "foo: agents/alice.athena.foo/chat.md"
    ]
    assert exit_code == 0
    repair.assert_called_once_with(("proj",))


def test_repair_manifest_dispatches_before_check_and_reports_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            committed=True,
            pushed=True,
            diagnostics=("foo: recovered",),
        ),
    )
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        repair_digests=False,
        repair_manifest=True,
    )
    with patch(
        "sase.agents.cli_sync.repair_agent_owner_manifests", return_value=outcomes
    ) as repair:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repair-manifest"
    assert payload["projects"][0]["diagnostics"] == ["foo: recovered"]
    assert exit_code == 0
    repair.assert_called_once_with(("proj",))


def test_names_forget_import_parser_accepts_machine_positional_and_options() -> None:
    dry_run = create_parser().parse_args(["agent", "names", "forget-import", "zeus"])
    apply = create_parser().parse_args(
        [
            "agent",
            "names",
            "forget-import",
            "zeus",
            "--transport",
            "v1",
            "--json",
            "--apply",
        ]
    )

    assert dry_run.names_subcommand == "forget-import"
    assert dry_run.machine == "zeus"
    assert dry_run.apply is False
    assert dry_run.transport == "v1"
    assert apply.apply and apply.json


def test_names_bare_usage_lists_both_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(names_subcommand=None)
    with pytest.raises(SystemExit) as exc_info:
        handle_agents_names(args)

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "forget-import" in output
    assert "migrate-auto" in output


def test_names_forget_import_cli_dispatches_and_reports_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcome = V1ForgetImportOutcome("zeus", True)
    args = argparse.Namespace(
        names_subcommand="forget-import",
        machine="zeus",
        apply=False,
        json=True,
    )
    with patch(
        "sase.agents_sync.v1_forget_import.forget_v1_import",
        return_value=outcome,
    ):
        with pytest.raises(SystemExit) as exc_info:
            handle_agents_names(args)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["machine"] == "zeus"
    assert payload["mode"] == "dry-run"
