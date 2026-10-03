"""Parser help tests for ``sase macro show``."""

from __future__ import annotations

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import (
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_macro_help_renders_show_in_sorted_subcommands() -> None:
    macro_parser = parser_for(("sase", "macro"))
    expected_commands = {"catalog", "expand", "explain", "graph", "list", "show"}

    help_text = macro_parser.format_help()
    help_commands = help_subcommand_rows(help_text, expected_commands)

    assert help_commands == sorted(expected_commands)
    assert "{catalog,expand,explain,graph,list,show}" in help_text


def test_macro_show_help_documents_flags_and_examples() -> None:
    help_text = flat_help(parser_for(("sase", "macro", "show")).format_help())

    assert "-c" in help_text
    assert "--color" in help_text
    assert "-f" in help_text
    assert "--format" in help_text
    assert "-p" in help_text
    assert "--project" in help_text
    assert "Show one macro or workflow definition" in help_text
    assert "sase macro show sase/reads" in help_text
    assert "sase macro show '#!sync'" in help_text
    assert "sase macro show plan --format json | jq .inputs" in help_text
    assert "sase macro show coder --format raw > coder.md" in help_text
    assert "sase macro show t --color always | less -R" in help_text


def test_bare_macro_still_delegates_to_list() -> None:
    args = create_parser().parse_args(["macro"])

    assert args.command == "macro"
    assert args.macro_subcommand == "list"


def test_legacy_xprompt_alias_parses_to_macro_parser() -> None:
    """The retired ``xprompt`` spelling still parses (flag gates dispatch)."""
    args = create_parser().parse_args(["xprompt", "list"])

    assert args.command == "xprompt"
    assert args.macro_subcommand == "list"


def test_narrowed_legacy_parser_still_parses() -> None:
    """``create_parser(only="xprompt")`` keeps working for legacy callers."""
    args = create_parser(only="xprompt").parse_args(["xprompt", "list"])

    assert args.command == "xprompt"
