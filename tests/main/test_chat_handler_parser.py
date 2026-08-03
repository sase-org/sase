"""Tests for the ``sase chat`` parser and command dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.history.chat_catalog_provenance import CHAT_PROVENANCE_VALUES
from sase.main.chat_handler import handle_chat_command
from sase.main.parser import create_parser

from tests.main.chat_handler_helpers import setup_fake_home


def test_parser_registers_chat_command() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "list", "-j", "-l", "5"])
    assert args.command == "chat"
    assert args.chat_subcommand == "list"
    assert args.json is True
    assert args.limit == 5


def test_parser_show_requires_a_selector() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show"])


def test_parser_show_rejects_multiple_selectors() -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-n", "alpha", "-p", "/tmp/x.md"])


def test_parser_show_format_choices() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "show", "-n", "alpha", "-f", "response"])
    assert args.agent == "alpha"
    assert args.format == "response"
    args = parser.parse_args(["chat", "show", "-b", "x", "-f", "resume"])
    assert args.basename == "x"
    assert args.format == "resume"
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-n", "alpha", "-f", "bogus"])


def test_parser_show_rejects_removed_prompt_rendering_selectors() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-b", "x", "-f", "xprompt"])
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-b", "x", "-f", "rendered"])
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-b", "x", "-x"])
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "show", "-b", "x", "--rendered"])


def test_parser_show_default_format_is_raw() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "show", "-p", "/tmp/x.md"])
    assert args.format == "raw"


def test_parser_list_short_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "list", "-q", "foo"])
    assert args.query == "foo"
    assert args.limit == 20  # default
    assert args.machine is None
    assert args.provenance is None


def test_parser_list_provenance_filters() -> None:
    parser = create_parser()
    args = parser.parse_args(["chat", "list", "-P", "remote", "-m", "zeus"])
    assert args.provenance == "remote"
    assert args.machine == "zeus"
    with pytest.raises(SystemExit):
        parser.parse_args(["chat", "list", "-P", "bogus"])


def test_parser_list_provenance_choices_match_catalog() -> None:
    """The CLI choices must not drift from the catalog's provenance states."""
    subparser = _chat_list_subparser()
    choices = next(
        tuple(action.choices or ())
        for action in subparser._actions  # noqa: SLF001 - argparse has no public view
        if action.dest == "provenance"
    )
    assert choices == CHAT_PROVENANCE_VALUES


def _chat_list_subparser() -> argparse.ArgumentParser:
    parser = create_parser()
    command_action = next(
        action
        for action in parser._actions  # noqa: SLF001 - argparse offers no public view
        if isinstance(action, argparse._SubParsersAction)
    )
    chat_parser = command_action.choices["chat"]
    chat_action = next(
        action
        for action in chat_parser._actions  # noqa: SLF001 - see above
        if isinstance(action, argparse._SubParsersAction)
    )
    return chat_action.choices["list"]


def test_dispatch_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    setup_fake_home(monkeypatch, tmp_path)
    args = argparse.Namespace(chat_subcommand="list", json=True, limit=5, query=None)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_command(args)
    assert excinfo.value.code == 0


def test_dispatch_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(chat_subcommand=None)
    with pytest.raises(SystemExit) as excinfo:
        handle_chat_command(args)
    assert excinfo.value.code == 1
    assert "Usage: sase chat" in capsys.readouterr().out
