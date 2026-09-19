"""Parser tests for ``sase tool``."""

from __future__ import annotations

import argparse

from sase.main.parser import create_parser, default_list_delegation_notice
from tests.main.parser_help_helpers import flat_help, parser_for


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def test_parser_defaults_bare_tool_to_list_with_notice() -> None:
    args = create_parser().parse_args(["tool"])

    assert args.command == "tool"
    assert args.tool_subcommand == "list"
    assert args.json is False
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase tool'; delegating to 'sase tool list'."
    )


def test_explicit_tool_list_prints_no_delegation_notice() -> None:
    args = create_parser().parse_args(["tool", "list", "-j"])
    assert args.json is True
    assert default_list_delegation_notice(args) is None


def test_tool_help_advertises_only_list() -> None:
    tool_parser = parser_for(("sase", "tool"))
    help_text = flat_help(tool_parser.format_help())
    subcommands = _subparser_action(tool_parser)

    assert list(subcommands.choices) == ["list"]
    assert "{list}" in help_text
    assert "run" not in subcommands.choices
    assert "runs" not in subcommands.choices
    assert "show" not in subcommands.choices
    assert "-j, --json" in flat_help(subcommands.choices["list"].format_help())
