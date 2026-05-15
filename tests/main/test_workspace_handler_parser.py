"""Tests for the ``sase workspace`` parser dispatch."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser
from sase.main.workspace_handler import handle_workspace_command
from tests.main.workspace_handler_helpers import make_args


class TestWorkspaceParser:
    def test_list_dispatch(self) -> None:
        ns = create_parser().parse_args(["workspace", "list", "-p", "demo", "-j"])
        assert ns.command == "workspace"
        assert ns.workspace_subcommand == "list"
        assert ns.project == "demo"
        assert ns.json is True

    def test_path_requires_number(self) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(["workspace", "path"])

    def test_cleanup_options(self) -> None:
        ns = create_parser().parse_args(
            ["workspace", "cleanup", "-s", "-i", "-n", "-p", "demo"]
        )
        assert ns.workspace_subcommand == "cleanup"
        assert ns.stale is True
        assert ns.include_shares is True
        assert ns.dry_run is True

    def test_repair_dry_run(self) -> None:
        ns = create_parser().parse_args(["workspace", "repair", "-n"])
        assert ns.workspace_subcommand == "repair"
        assert ns.dry_run is True

    def test_unknown_subcommand_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = make_args(workspace_subcommand=None)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "Usage" in capsys.readouterr().err
