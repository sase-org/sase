"""Parser help tests for ``sase xprompt show``."""

from __future__ import annotations

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import (
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_xprompt_help_renders_show_in_sorted_subcommands() -> None:
    xprompt_parser = parser_for(("sase", "xprompt"))
    expected_commands = {"catalog", "expand", "explain", "graph", "list", "show"}

    help_text = xprompt_parser.format_help()
    help_commands = help_subcommand_rows(help_text, expected_commands)

    assert help_commands == sorted(expected_commands)
    assert "{catalog,expand,explain,graph,list,show}" in help_text


def test_xprompt_show_help_documents_flags_and_examples() -> None:
    help_text = flat_help(parser_for(("sase", "xprompt", "show")).format_help())

    assert "-c" in help_text
    assert "--color" in help_text
    assert "-f" in help_text
    assert "--format" in help_text
    assert "-p" in help_text
    assert "--project" in help_text
    assert "Show one xprompt or workflow definition" in help_text
    assert "sase xprompt show sase/reads" in help_text
    assert "sase xprompt show '#!sync'" in help_text
    assert "sase xprompt show plan --format json | jq .inputs" in help_text
    assert "sase xprompt show coder --format raw > coder.md" in help_text
    assert "sase xprompt show t --color always | less -R" in help_text


def test_bare_xprompt_still_delegates_to_list() -> None:
    args = create_parser().parse_args(["xprompt"])

    assert args.command == "xprompt"
    assert args.xprompt_subcommand == "list"
