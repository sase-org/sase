"""Tests for the ``sase vcs`` parser and handler dispatch."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser


class TestVcsParser:
    def test_bare_vcs_defaults_to_log(self) -> None:
        ns = create_parser().parse_args(["vcs"])

        assert ns.command == "vcs"
        assert ns.vcs_subcommand == "log"
        assert ns.limit == 20
        assert ns.repos == []
        assert ns.current_only is False
        assert ns.format == "pretty"
        assert ns.color == "auto"

    def test_log_defaults(self) -> None:
        ns = create_parser().parse_args(["vcs", "log"])

        assert ns.vcs_subcommand == "log"
        assert ns.limit == 20
        assert ns.format == "pretty"
        assert ns.color == "auto"

    def test_log_limit_and_format_and_color(self) -> None:
        ns = create_parser().parse_args(
            ["vcs", "log", "-n", "5", "--format", "json", "--color", "never"]
        )

        assert ns.limit == 5
        assert ns.format == "json"
        assert ns.color == "never"

    def test_log_repo_is_repeatable(self) -> None:
        ns = create_parser().parse_args(
            ["vcs", "log", "-r", "sase", "--repo", "sase-core"]
        )

        assert ns.repos == ["sase", "sase-core"]

    def test_log_current_only_flag(self) -> None:
        ns = create_parser().parse_args(["vcs", "log", "--current-only"])

        assert ns.current_only is True

    def test_log_rejects_non_positive_limit(self) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(["vcs", "log", "-n", "0"])

    def test_log_rejects_unknown_format(self) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(["vcs", "log", "--format", "fancy"])


class TestVcsHandlerDispatch:
    def test_unknown_subcommand_exits_2(self) -> None:
        from sase.main.vcs_handler import handle_vcs_command

        ns = argparse.Namespace(vcs_subcommand="bogus")
        with pytest.raises(SystemExit) as excinfo:
            handle_vcs_command(ns)
        assert excinfo.value.code == 2

    def test_missing_subcommand_exits_2(self) -> None:
        from sase.main.vcs_handler import handle_vcs_command

        ns = argparse.Namespace(vcs_subcommand=None)
        with pytest.raises(SystemExit) as excinfo:
            handle_vcs_command(ns)
        assert excinfo.value.code == 2
