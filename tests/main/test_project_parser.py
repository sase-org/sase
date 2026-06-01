"""Tests for the ``sase project`` parser."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser


class TestProjectParser:
    def test_bare_project_defaults_to_list_active(self) -> None:
        ns = create_parser().parse_args(["project"])

        assert ns.command == "project"
        assert ns.project_subcommand == "list"
        assert ns.state == "active"
        assert ns.json is False

    def test_list_options(self) -> None:
        ns = create_parser().parse_args(["project", "list", "-s", "all", "-j"])

        assert ns.project_subcommand == "list"
        assert ns.state == "all"
        assert ns.json is True

    def test_show_json_option(self) -> None:
        ns = create_parser().parse_args(["project", "show", "demo", "--json"])

        assert ns.project_subcommand == "show"
        assert ns.project == "demo"
        assert ns.json is True

    def test_set_state_force_option(self) -> None:
        ns = create_parser().parse_args(
            ["project", "set-state", "demo", "archived", "-f"]
        )

        assert ns.project_subcommand == "set-state"
        assert ns.project == "demo"
        assert ns.state == "archived"
        assert ns.force is True

    def test_alias_force_option(self) -> None:
        ns = create_parser().parse_args(["project", "close", "demo", "--force"])

        assert ns.project_subcommand == "close"
        assert ns.project == "demo"
        assert ns.force is True

    @pytest.mark.parametrize(
        "argv",
        [
            ["project", "list", "--state", "paused"],
            ["project", "set-state", "demo", "paused"],
        ],
    )
    def test_invalid_states_exit(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(argv)
