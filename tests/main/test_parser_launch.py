"""Tests for the launch approval parser command group."""

from __future__ import annotations

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for


def test_launch_command_group_parses_subcommands() -> None:
    """``sase launch`` resolves pending LaunchApproval requests."""
    parser = create_parser()

    approve_args = parser.parse_args(["launch", "approve", "launch-1"])
    reject_args = parser.parse_args(
        ["launch", "reject", "launch-1", "-f", "Narrow the request"]
    )

    assert approve_args.command == "launch"
    assert approve_args.launch_subcommand == "approve"
    assert approve_args.selector == "launch-1"
    assert reject_args.launch_subcommand == "reject"
    assert reject_args.selector == "launch-1"
    assert reject_args.feedback == "Narrow the request"


def test_launch_help_renders_sorted_subcommands() -> None:
    """``sase launch --help`` lists child commands alphabetically."""
    launch_parser = parser_for(("sase", "launch"))
    expected_commands = {"approve", "reject"}

    help_commands = help_subcommand_rows(launch_parser.format_help(), expected_commands)

    assert help_commands == sorted(expected_commands)


def test_launch_public_long_options_have_short_aliases() -> None:
    """Every public long option under ``sase launch`` has a short alias."""
    parser = parser_for(("sase", "launch", "reject"))
    for action in parser._actions:
        public_long_options = [
            option
            for option in action.option_strings
            if option.startswith("--") and option != "--help"
        ]
        if not public_long_options:
            continue
        short_options = [
            option
            for option in action.option_strings
            if option.startswith("-") and not option.startswith("--")
        ]
        assert short_options, "sase launch reject " + "/".join(public_long_options)
