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


def test_tool_help_advertises_implemented_verbs() -> None:
    tool_parser = parser_for(("sase", "tool"))
    help_text = flat_help(tool_parser.format_help())
    subcommands = _subparser_action(tool_parser)

    assert list(subcommands.choices) == ["list", "run", "runs", "show"]
    assert "{list,run,runs,show}" in help_text
    assert "-j, --json" in flat_help(subcommands.choices["list"].format_help())


def test_tool_run_preserves_remainder_after_separator() -> None:
    args = create_parser().parse_args(
        ["tool", "run", "-q", "-T", "5", "--", "printf", "--", "-n"]
    )
    assert args.quiet is True
    assert args.tail_lines == 5
    assert args.tool_run_words == ["--", "printf", "--", "-n"]


def test_tool_run_named_extra_args_keep_leading_dashes() -> None:
    args = create_parser().parse_args(["tool", "run", "test", "--", "-k", "not-a-flag"])
    assert args.tool_run_words == ["test", "--", "-k", "not-a-flag"]


def test_tool_runs_and_show_flags() -> None:
    runs = create_parser().parse_args(
        ["tool", "runs", "-a", "-A", "agent-1", "-n", "20", "-s", "failed", "-j"]
    )
    assert runs.tool_runs_all is True
    assert runs.tool_runs_agent == "agent-1"
    assert runs.tool_runs_limit == 20
    assert runs.tool_runs_state == "failed"
    assert runs.tool_runs_json is True

    show = create_parser().parse_args(["tool", "show", "abc123", "-l"])
    assert show.tool_show_run_id == "abc123"
    assert show.tool_show_logs is True
    assert show.tool_show_json is False
