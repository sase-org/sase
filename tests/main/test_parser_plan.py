"""Tests for the plan parser command group."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for


def test_plan_command_group_parses_subcommands() -> None:
    """``sase plan`` is a command group with list/propose/approve/reject children."""
    parser = create_parser()

    bare_args = parser.parse_args(["plan"])
    list_args = parser.parse_args(["plan", "list"])
    propose_args = parser.parse_args(["plan", "propose", "file.md"])
    approve_args = parser.parse_args(
        [
            "plan",
            "approve",
            "abcdef12",
            "-k",
            "tale",
            "-m",
            "worker",
            "-p",
            "Focus tests",
        ]
    )

    assert bare_args.command == "plan"
    assert bare_args.plan_subcommand == "list"
    assert list_args.plan_subcommand == "list"
    assert propose_args.plan_subcommand == "propose"
    assert propose_args.plan_file == "file.md"
    assert approve_args.plan_subcommand == "approve"
    assert approve_args.selector == "abcdef12"
    assert approve_args.kind == "tale"
    assert approve_args.model == "worker"
    assert approve_args.prompt == "Focus tests"


def test_plan_reject_parses_with_optional_selector() -> None:
    """``sase plan reject`` accepts an optional notification selector."""
    parser = create_parser()

    reject_args = parser.parse_args(["plan", "reject", "abcdef12"])
    bare_reject_args = parser.parse_args(["plan", "reject"])

    assert reject_args.plan_subcommand == "reject"
    assert reject_args.selector == "abcdef12"
    assert bare_reject_args.plan_subcommand == "reject"
    assert bare_reject_args.selector is None


def test_plan_list_parses_status_and_limit_options() -> None:
    """``sase plan list`` accepts repeatable statuses and history limits."""
    parser = create_parser()

    default_args = parser.parse_args(["plan", "list"])
    filtered_args = parser.parse_args(
        [
            "plan",
            "list",
            "-s",
            "approved",
            "--status",
            "rejected",
            "--limit",
            "0",
        ]
    )

    assert default_args.limit == 10
    assert default_args.status is None
    assert filtered_args.status == ["approved", "rejected"]
    assert filtered_args.limit == 0


@pytest.mark.parametrize(
    "arguments",
    (
        ["plan", "list", "--status", "wip"],
        ["plan", "list", "--limit", "-1"],
    ),
)
def test_plan_list_rejects_invalid_status_and_limit(arguments: list[str]) -> None:
    """Plan-list filters use strict statuses and a nonnegative limit."""
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(arguments)

    assert exc_info.value.code == 2


def test_plan_command_rejects_old_root_plan_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase plan <file>`` is no longer accepted; use ``propose``."""
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["plan", "file.md"])

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "invalid choice" in stderr
    assert "propose" in stderr


def test_plan_help_renders_sorted_subcommands() -> None:
    """``sase plan --help`` lists child commands alphabetically."""
    plan_parser = parser_for(("sase", "plan"))
    expected_commands = {"approve", "list", "propose", "reject", "search"}

    help_commands = help_subcommand_rows(plan_parser.format_help(), expected_commands)
    help_text = plan_parser.format_help()

    assert help_commands == sorted(expected_commands)
    assert "With no subcommand, `sase plan` defaults to `sase plan list`." in help_text
    assert "sase plan propose sase_plan_feature.md" in help_text
    assert "sase plan reject abcdef12" in help_text


def test_plan_subcommand_help_is_complete() -> None:
    """Plan child help documents public options and examples."""
    approve_help = parser_for(("sase", "plan", "approve")).format_help()
    list_help = parser_for(("sase", "plan", "list")).format_help()
    propose_help = parser_for(("sase", "plan", "propose")).format_help()
    reject_help = parser_for(("sase", "plan", "reject")).format_help()

    assert "SELECTOR" in reject_help
    assert "Notification id or unique prefix" in reject_help
    assert "If SELECTOR is omitted, exactly one" in reject_help
    assert "sase plan reject abcdef12" in reject_help

    assert "{approve,commit,epic,tale}" in approve_help
    assert "-k {approve,commit,epic,tale}" in approve_help
    assert "--kind {approve,commit,epic,tale}" in approve_help
    assert "-m MODEL" in approve_help
    assert "--model MODEL" in approve_help
    assert "-p PROMPT" in approve_help
    assert "--prompt PROMPT" in approve_help
    assert "sase plan approve abcdef12 --kind tale --prompt 'Focus tests'" in (
        approve_help
    )
    assert "-j" in list_help
    assert "--json" in list_help
    assert "-n LIMIT" in list_help
    assert "--limit LIMIT" in list_help
    assert "-s {approved,proposed,rejected}" in list_help
    assert "--status {approved,proposed,rejected}" in list_help
    assert "sase plan list --json" in list_help
    assert "sase plan list --status approved --limit 25" in list_help
    assert "sase plan list -s proposed" in list_help
    assert "sase plan list -s rejected -n 0" in list_help
    assert "PLAN_FILE" in propose_help
    assert "sase plan propose sase_plan_feature.md" in propose_help


def test_plan_public_long_options_have_short_aliases() -> None:
    """Every public long option under ``sase plan`` has a short alias."""
    for path in (
        ("sase", "plan", "approve"),
        ("sase", "plan", "list"),
        ("sase", "plan", "propose"),
        ("sase", "plan", "reject"),
    ):
        parser = parser_for(path)
        for action in parser._actions:
            long_options = [
                option for option in action.option_strings if option.startswith("--")
            ]
            public_long_options = [
                option for option in long_options if option != "--help"
            ]
            if not public_long_options:
                continue

            short_options = [
                option
                for option in action.option_strings
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, " ".join((*path, "/".join(public_long_options)))
