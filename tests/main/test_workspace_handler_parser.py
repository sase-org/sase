"""Tests for the ``sase workspace`` parser dispatch."""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch

from sase.main.workspace_handler import handle_workspace_command
from sase.workspace_provider.inventory import WorkspaceInventory
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.workspace_handler_helpers import make_args


class TestWorkspaceParser:
    def test_list_dispatch(self) -> None:
        ns = parse_sase_args(["workspace", "list", "-p", "demo", "-j"])
        assert ns.command == "workspace"
        assert ns.workspace_subcommand == "list"
        assert ns.project == "demo"
        assert ns.json is True

    def test_list_all_projects_option(self) -> None:
        ns = parse_sase_args(["workspace", "list", "--all"])
        assert ns.workspace_subcommand == "list"
        assert ns.all_projects is True

    def test_list_all_projects_json(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ns = parse_sase_args(["workspace", "list", "--all", "--json"])
        with (
            patch(
                "sase.main.workspace_handler_list.collect_workspace_inventory",
                return_value=WorkspaceInventory(records=(), projects=()),
            ) as collect,
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_workspace_command(ns)

        assert exc_info.value.code == 0
        collect.assert_called_once_with(include_disabled=True)
        assert json.loads(capsys.readouterr().out)["workspaces"] == []

    def test_path_requires_number(self) -> None:
        with pytest.raises(SystemExit):
            parse_sase_args(["workspace", "path"])

    @pytest.mark.parametrize("flag", ["-c", "--clean"])
    def test_open_clean_flag(self, flag: str) -> None:
        ns = parse_sase_args(["workspace", "open", flag, "-r", "prep checkout", "12"])
        assert ns.workspace_subcommand == "open"
        assert ns.workspace_num == 12
        assert ns.clean is True
        assert ns.reason == "prep checkout"

    def test_open_print_flag_is_accepted_for_compatibility(self) -> None:
        ns = parse_sase_args(
            ["workspace", "open", "--print", "-r", "prep checkout", "12"]
        )
        assert ns.workspace_subcommand == "open"
        assert ns.workspace_num == 12
        assert ns.print_path is True

    @pytest.mark.parametrize("flag", ["-r", "--reason"])
    def test_open_reason_flag_parses(self, flag: str) -> None:
        ns = parse_sase_args(["workspace", "open", flag, "debugging a sibling", "12"])
        assert ns.workspace_subcommand == "open"
        assert ns.workspace_num == 12
        assert ns.reason == "debugging a sibling"

    def test_open_requires_reason(self) -> None:
        with pytest.raises(SystemExit):
            parse_sase_args(["workspace", "open", "12"])

    def test_cleanup_options(self) -> None:
        ns = parse_sase_args(["workspace", "cleanup", "-s", "-i", "-n", "-p", "demo"])
        assert ns.workspace_subcommand == "cleanup"
        assert ns.stale is True
        assert ns.include_shares is True
        assert ns.dry_run is True

    def test_repair_dry_run(self) -> None:
        ns = parse_sase_args(["workspace", "repair", "-n"])
        assert ns.workspace_subcommand == "repair"
        assert ns.dry_run is True

    def test_unknown_subcommand_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = make_args(workspace_subcommand=None)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "Usage" in capsys.readouterr().err
