"""Tests for the ``sase glossary`` parser and command dispatch."""

from __future__ import annotations

import argparse

import pytest

from sase.main import glossary_handler
from sase.main.parser import create_parser
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for


def _no_glossary_web(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every dispatch test onto the legacy config-backed branch.

    These tests exercise pure dispatch mechanics, not the compat delegation
    added in the `glossary` memory-web migration; without this, dispatch
    would probe the real filesystem for a `glossary` memory web at the
    current working directory.
    """
    monkeypatch.setattr(glossary_handler, "find_glossary_web", lambda *_a, **_kw: None)


def test_parser_registers_glossary_namespace() -> None:
    parser = create_parser()

    default_args = parser.parse_args(["glossary"])
    assert default_args.command == "glossary"
    assert default_args.glossary_subcommand == "list"

    list_args = parser.parse_args(
        [
            "glossary",
            "list",
            "hood",
            "--definitions",
            "--format",
            "json",
            "--project",
            "sase",
        ]
    )
    assert list_args.command == "glossary"
    assert list_args.glossary_subcommand == "list"
    assert list_args.pattern == "hood"
    assert list_args.definitions is True
    assert list_args.format == "json"
    assert list_args.project == "sase"

    show_args = parser.parse_args(
        [
            "glossary",
            "show",
            "Agent Hood",
            "Stitch",
            "-d",
            "0",
            "-f",
            "markdown",
        ]
    )
    assert show_args.command == "glossary"
    assert show_args.glossary_subcommand == "show"
    assert show_args.term == ["Agent Hood", "Stitch"]
    assert show_args.depth == 0
    assert show_args.format == "markdown"

    read_args = parser.parse_args(
        [
            "glossary",
            "read",
            "Agent Hood",
            "-d",
            "1",
            "-f",
            "json",
            "-r",
            "Need hood",
        ]
    )
    assert read_args.command == "glossary"
    assert read_args.glossary_subcommand == "read"
    assert read_args.term == ["Agent Hood"]
    assert read_args.depth == 1
    assert read_args.format == "json"
    assert read_args.reason == "Need hood"

    log_args = parser.parse_args(
        [
            "glossary",
            "log",
            "-a",
            "agent-a",
            "-f",
            "json",
            "-i",
            "read-a",
            "-t",
            "Stitch",
        ]
    )
    assert log_args.command == "glossary"
    assert log_args.glossary_subcommand == "log"
    assert log_args.agent == "agent-a"
    assert log_args.format == "json"
    assert log_args.id == "read-a"
    assert log_args.term == "Stitch"

    add_args = parser.parse_args(
        [
            "glossary",
            "add",
            "Test Term",
            "A test term.",
            "-a",
            "tt",
            "-a",
            "test",
            "-f",
            "json",
            "-I",
            "-p",
            "sase",
        ]
    )
    assert add_args.command == "glossary"
    assert add_args.glossary_subcommand == "add"
    assert add_args.term == "Test Term"
    assert add_args.definition == "A test term."
    assert add_args.alias == ["tt", "test"]
    assert add_args.format == "json"
    assert add_args.no_init is True
    assert add_args.project == "sase"

    del_args = parser.parse_args(
        ["glossary", "del", "tt", "-f", "rich", "-n", "-I", "-p", "sase"]
    )
    assert del_args.command == "glossary"
    assert del_args.glossary_subcommand == "del"
    assert del_args.term == "tt"
    assert del_args.format == "rich"
    assert del_args.dry_run is True
    assert del_args.no_init is True
    assert del_args.project == "sase"

    all_args = parser.parse_args(["glossary", "all", "-f", "markdown", "-p", "sase"])
    assert all_args.command == "glossary"
    assert all_args.glossary_subcommand == "all"
    assert all_args.format == "markdown"
    assert all_args.project == "sase"

    all_default = parser.parse_args(["glossary", "all"])
    assert all_default.format == "rich"


def test_parser_read_requires_reason() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["glossary", "read", "Stitch"])


def test_parser_glossary_help_lists_subcommands_alphabetically() -> None:
    glossary_parser = parser_for(("sase", "glossary"))
    expected = {"add", "all", "del", "list", "log", "read", "show"}

    help_text = glossary_parser.format_help()
    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{add,all,del,list,log,read,show}" in help_text


def test_parser_accepts_project_before_or_after_subcommand() -> None:
    parser = create_parser()

    before = parser.parse_args(["glossary", "-p", "sase", "show", "Stitch"])
    after = parser.parse_args(["glossary", "show", "Stitch", "-p", "sase"])
    read_before = parser.parse_args(
        ["glossary", "-p", "sase", "read", "Stitch", "-r", "Need stitch"]
    )
    read_after = parser.parse_args(
        ["glossary", "read", "Stitch", "-p", "sase", "-r", "Need stitch"]
    )
    log_before = parser.parse_args(["glossary", "-p", "sase", "log"])
    log_after = parser.parse_args(["glossary", "log", "-p", "sase"])
    add_before = parser.parse_args(
        ["glossary", "-p", "sase", "add", "Term", "A definition."]
    )
    add_after = parser.parse_args(
        ["glossary", "add", "Term", "A definition.", "-p", "sase"]
    )
    del_before = parser.parse_args(["glossary", "-p", "sase", "del", "Term"])
    del_after = parser.parse_args(["glossary", "del", "Term", "-p", "sase"])
    all_before = parser.parse_args(["glossary", "-p", "sase", "all"])
    all_after = parser.parse_args(["glossary", "all", "-p", "sase"])

    assert before.project == "sase"
    assert after.project == "sase"
    assert read_before.project == "sase"
    assert read_after.project == "sase"
    assert log_before.project == "sase"
    assert log_after.project == "sase"
    assert add_before.project == "sase"
    assert add_after.project == "sase"
    assert del_before.project == "sase"
    assert del_after.project == "sase"
    assert all_before.project == "sase"
    assert all_after.project == "sase"


def test_parser_project_before_subcommand_survives_subparser_default() -> None:
    parser = create_parser()

    args = parser.parse_args(["glossary", "-p", "sase", "list"])

    assert args.project == "sase"


def test_parser_glossary_depth_rejects_negative() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["glossary", "show", "Stitch", "-d", "-1"])


def test_glossary_all_dispatches_to_all_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_all(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr("sase.glossary.cli_all.handle_glossary_all_command", fake_all)
    args = create_parser().parse_args(["glossary", "all"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_glossary_add_dispatches_to_add_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_add(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr("sase.glossary.cli_add.handle_glossary_add_command", fake_add)
    args = create_parser().parse_args(["glossary", "add", "Term", "A definition."])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_glossary_del_dispatches_to_del_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_del(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr("sase.glossary.cli_del.handle_glossary_del_command", fake_del)
    args = create_parser().parse_args(["glossary", "del", "Term"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_glossary_list_dispatches_to_list_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_list(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.glossary.cli_list.handle_glossary_list_command", fake_list
    )
    args = create_parser().parse_args(["glossary", "list"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_glossary_show_dispatches_to_show_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_show(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.glossary.cli_show.handle_glossary_show_command", fake_show
    )
    args = create_parser().parse_args(["glossary", "show", "Stitch"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_glossary_read_dispatches_to_read_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_read(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.glossary.cli_read.handle_glossary_read_command", fake_read
    )
    args = create_parser().parse_args(
        ["glossary", "read", "Stitch", "-r", "Need stitch"]
    )

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_glossary_log_dispatches_to_log_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_log(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr("sase.glossary.cli_log.handle_glossary_log_command", fake_log)
    args = create_parser().parse_args(["glossary", "log"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_bare_glossary_defaults_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_glossary_web(monkeypatch)
    calls: list[argparse.Namespace] = []

    def fake_list(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(
        "sase.glossary.cli_list.handle_glossary_list_command", fake_list
    )
    args = create_parser().parse_args(["glossary"])

    with pytest.raises(SystemExit) as exc:
        glossary_handler.handle_glossary_command(args)

    assert exc.value.code == 0
    assert calls == [args]
