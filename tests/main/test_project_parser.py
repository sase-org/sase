"""Tests for the ``sase project`` parser."""

from __future__ import annotations

from tests.main.parser_cli_helpers import parse_sase_args


class TestProjectParser:
    def test_bare_project_defaults_to_list_enabled(self) -> None:
        ns = parse_sase_args(["project"])

        assert ns.command == "project"
        assert ns.project_subcommand == "list"
        assert ns.state == "enabled"
        assert ns.json is False

    def test_list_options(self) -> None:
        ns = parse_sase_args(["project", "list", "-s", "all", "-j"])

        assert ns.project_subcommand == "list"
        assert ns.state == "all"
        assert ns.json is True

    def test_list_sibling_state_option(self) -> None:
        ns = parse_sase_args(["project", "list", "-s", "sibling"])

        assert ns.project_subcommand == "list"
        assert ns.state == "sibling"

    def test_show_json_option(self) -> None:
        ns = parse_sase_args(["project", "show", "demo", "--json"])

        assert ns.project_subcommand == "show"
        assert ns.project == "demo"
        assert ns.json is True

    def test_current_defaults(self) -> None:
        ns = parse_sase_args(["project", "current"])

        assert ns.project_subcommand == "current"
        assert ns.json is False

    def test_current_json_short_option(self) -> None:
        ns = parse_sase_args(["project", "current", "-j"])

        assert ns.project_subcommand == "current"
        assert ns.json is True

    def test_current_json_long_option(self) -> None:
        ns = parse_sase_args(["project", "current", "--json"])

        assert ns.project_subcommand == "current"
        assert ns.json is True

    def test_set_current_json_option(self) -> None:
        ns = parse_sase_args(["project", "set-current", "demo", "-j"])

        assert ns.project_subcommand == "set-current"
        assert ns.project == "demo"
        assert ns.json is True

    def test_alias_list_defaults(self) -> None:
        ns = parse_sase_args(["project", "alias"])

        assert ns.project_subcommand == "alias"
        assert ns.alias_subcommand == "list"
        assert ns.project is None
        assert ns.json is False

    def test_alias_list_project_json_option(self) -> None:
        ns = parse_sase_args(["project", "alias", "list", "demo", "-j"])

        assert ns.project_subcommand == "alias"
        assert ns.alias_subcommand == "list"
        assert ns.project == "demo"
        assert ns.json is True

    def test_alias_add_remove_clear_parse(self) -> None:
        add = parse_sase_args(["project", "alias", "add", "demo", "docs"])
        remove = parse_sase_args(["project", "alias", "remove", "demo", "docs"])
        clear = parse_sase_args(["project", "alias", "clear", "demo"])

        assert add.project_subcommand == "alias"
        assert add.alias_subcommand == "add"
        assert add.project == "demo"
        assert add.alias == "docs"
        assert remove.alias_subcommand == "remove"
        assert remove.project == "demo"
        assert remove.alias == "docs"
        assert clear.alias_subcommand == "clear"
        assert clear.project == "demo"

    def test_set_state_force_option(self) -> None:
        ns = parse_sase_args(["project", "set-state", "demo", "disabled", "-f"])

        assert ns.project_subcommand == "set-state"
        assert ns.project == "demo"
        assert ns.state == "disabled"
        assert ns.force is True

    def test_set_state_sibling_option(self) -> None:
        ns = parse_sase_args(["project", "set-state", "demo", "sibling"])

        assert ns.project_subcommand == "set-state"
        assert ns.project == "demo"
        assert ns.state == "sibling"

    def test_disable_force_option(self) -> None:
        ns = parse_sase_args(["project", "disable", "demo", "--force"])

        assert ns.project_subcommand == "disable"
        assert ns.project == "demo"
        assert ns.force is True

    def test_legacy_aliases_still_parse(self) -> None:
        set_state = parse_sase_args(["project", "set-state", "demo", "archived"])
        close = parse_sase_args(["project", "close", "demo"])
        activate = parse_sase_args(["project", "activate", "demo"])
        deactivate = parse_sase_args(["project", "deactivate", "demo"])

        assert set_state.project_subcommand == "set-state"
        assert set_state.state == "archived"
        assert close.project_subcommand == "close"
        assert activate.project_subcommand == "activate"
        assert deactivate.project_subcommand == "deactivate"
