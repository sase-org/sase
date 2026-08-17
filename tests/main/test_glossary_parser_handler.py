"""Tests for the ``sase glossary`` parser and command dispatch."""

from __future__ import annotations

import argparse

import pytest

from sase.main import glossary_handler
from sase.main.parser import create_parser


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


def test_parser_accepts_project_before_or_after_subcommand() -> None:
    parser = create_parser()

    before = parser.parse_args(["glossary", "-p", "sase", "show", "Stitch"])
    after = parser.parse_args(["glossary", "show", "Stitch", "-p", "sase"])

    assert before.project == "sase"
    assert after.project == "sase"


def test_parser_project_before_subcommand_survives_subparser_default() -> None:
    parser = create_parser()

    args = parser.parse_args(["glossary", "-p", "sase", "list"])

    assert args.project == "sase"


def test_parser_glossary_depth_rejects_negative() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["glossary", "show", "Stitch", "-d", "-1"])


def test_glossary_list_dispatches_to_list_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_bare_glossary_defaults_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
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
