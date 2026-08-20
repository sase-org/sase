"""Tests for the ``sase snippet`` parser and command dispatch."""

from __future__ import annotations

import argparse

import pytest

from sase.main import snippet_handler
from sase.main.parser import create_parser, default_list_delegation_notice
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    help_subcommand_rows,
    parser_for,
)


def test_parser_registers_snippet_namespace() -> None:
    parser = create_parser()

    default_args = parser.parse_args(["snippet"])
    assert default_args.command == "snippet"
    assert default_args.snippet_subcommand == "list"
    assert default_args.format == "table"
    assert default_args.pattern is None
    assert default_args.definitions is False

    list_args = parser.parse_args(
        [
            "snippet",
            "list",
            "todo",
            "--definitions",
            "--format",
            "json",
            "--project",
            "sase",
        ]
    )
    assert list_args.snippet_subcommand == "list"
    assert list_args.pattern == "todo"
    assert list_args.definitions is True
    assert list_args.format == "json"
    assert list_args.project == "sase"

    show_args = parser.parse_args(["snippet", "show", "greet", "-f", "markdown"])
    assert show_args.snippet_subcommand == "show"
    assert show_args.trigger == "greet"
    assert show_args.format == "markdown"

    add_args = parser.parse_args(
        [
            "snippet",
            "add",
            "todo",
            "TODO($1)$0",
            "-F",
            "-n",
            "-f",
            "json",
            "-p",
            "sase",
            "-t",
            "/tmp/sase.yml",
        ]
    )
    assert add_args.snippet_subcommand == "add"
    assert add_args.trigger == "todo"
    assert add_args.template == "TODO($1)$0"
    assert add_args.force is True
    assert add_args.dry_run is True
    assert add_args.format == "json"
    assert add_args.project == "sase"
    assert add_args.target == "/tmp/sase.yml"

    delete_args = parser.parse_args(
        ["snippet", "delete", "todo", "-a", "-n", "-f", "json", "-p", "sase"]
    )
    assert delete_args.snippet_subcommand == "delete"
    assert delete_args.trigger == "todo"
    assert delete_args.all_layers is True
    assert delete_args.dry_run is True
    assert delete_args.format == "json"
    assert delete_args.project == "sase"


def test_parser_snippet_help_lists_subcommands_alphabetically() -> None:
    snippet_parser = parser_for(("sase", "snippet"))
    expected = {"add", "delete", "list", "show"}

    help_text = snippet_parser.format_help()
    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{add,delete,list,show}" in help_text
    assert "defaults to `sase snippet list`" in help_text


def test_parser_snippet_options_are_alphabetical_and_aliased() -> None:
    add_help = parser_for(("sase", "snippet", "add")).format_help()
    delete_help = parser_for(("sase", "snippet", "delete")).format_help()
    list_help = parser_for(("sase", "snippet", "list")).format_help()
    show_help = parser_for(("sase", "snippet", "show")).format_help()

    add_options = ["--dry-run", "--force", "--format", "--project", "--target"]
    delete_options = ["--all", "--dry-run", "--format", "--project"]
    list_options = ["--definitions", "--format", "--project"]
    show_options = ["--format", "--project"]
    _assert_long_option_order(add_help, add_options)
    _assert_long_option_order(delete_help, delete_options)
    _assert_long_option_order(list_help, list_options)
    _assert_long_option_order(show_help, show_options)

    assert_metavar_option_documented(add_help, "-t", "--target", "PATH")
    assert_metavar_option_documented(add_help, "-p", "--project", "REF")
    assert "-F, --force" in add_help
    assert "-n, --dry-run" in add_help
    assert "-a, --all" in delete_help
    assert "-d, --definitions" in list_help


def test_parser_accepts_project_before_or_after_subcommand() -> None:
    parser = create_parser()

    before = parser.parse_args(["snippet", "-p", "sase", "show", "greet"])
    after = parser.parse_args(["snippet", "show", "greet", "-p", "sase"])
    add_before = parser.parse_args(["snippet", "-p", "sase", "add", "todo", "TODO$0"])
    add_after = parser.parse_args(["snippet", "add", "todo", "TODO$0", "-p", "sase"])
    list_before = parser.parse_args(["snippet", "-p", "sase", "list"])
    delete_after = parser.parse_args(["snippet", "delete", "todo", "-p", "sase"])

    assert before.project == "sase"
    assert after.project == "sase"
    assert add_before.project == "sase"
    assert add_after.project == "sase"
    assert list_before.project == "sase"
    assert delete_after.project == "sase"


def test_bare_snippet_records_list_delegation() -> None:
    parser = create_parser()
    omitted = parser.parse_args(["snippet"])
    explicit = parser.parse_args(["snippet", "list"])

    assert default_list_delegation_notice(omitted) == (
        "No subcommand provided for 'sase snippet'; delegating to 'sase snippet list'."
    )
    assert default_list_delegation_notice(explicit) is None


def test_snippet_add_dispatches_to_add_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_dispatches(
        monkeypatch,
        ["snippet", "add", "todo", "TODO$0"],
        "sase.snippet.cli_add.handle_snippet_add_command",
    )


def test_snippet_delete_dispatches_to_delete_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_dispatches(
        monkeypatch,
        ["snippet", "delete", "todo"],
        "sase.snippet.cli_delete.handle_snippet_delete_command",
    )


def test_snippet_list_dispatches_to_list_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_dispatches(
        monkeypatch,
        ["snippet", "list"],
        "sase.snippet.cli_list.handle_snippet_list_command",
    )


def test_snippet_show_dispatches_to_show_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_dispatches(
        monkeypatch,
        ["snippet", "show", "todo"],
        "sase.snippet.cli_show.handle_snippet_show_command",
    )


def test_bare_snippet_defaults_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_dispatches(
        monkeypatch,
        ["snippet"],
        "sase.snippet.cli_list.handle_snippet_list_command",
    )


def _assert_dispatches(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], target: str
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_handler(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(target, fake_handler)
    args = create_parser().parse_args(argv)

    with pytest.raises(SystemExit) as exc:
        snippet_handler.handle_snippet_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def _assert_long_option_order(help_text: str, options: list[str]) -> None:
    options_text = help_text.split("options:", 1)[1]
    assert [options_text.index(option) for option in options] == sorted(
        options_text.index(option) for option in options
    )
