"""Tests for the ``sase artifact`` CLI parser and dispatch glue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from sase.main import artifact_handler, entry
from sase.main.parser import create_parser

from tests.main.artifact_cli_helpers import artifact_parser, subparser_action


def test_artifact_parser_registers_required_subcommands() -> None:
    parser = artifact_parser()

    assert set(subparser_action(parser).choices) == {
        "add",
        "remove",
        "list",
        "show",
        "graph",
        "rebuild",
        "doctor",
    }


def test_artifact_options_all_have_short_forms() -> None:
    parser = artifact_parser()

    for name, subcommand_parser in subparser_action(parser).choices.items():
        for action in subcommand_parser._actions:
            if not action.option_strings:
                continue
            if action.dest == "help":
                continue
            assert any(
                option.startswith("-") and not option.startswith("--")
                for option in action.option_strings
            ), f"sase artifact {name} {action.dest}"


def test_artifact_docs_cover_registered_subcommands() -> None:
    docs_path = Path(__file__).parents[2] / "docs" / "artifacts.md"
    docs = docs_path.read_text()
    subcommands = subparser_action(artifact_parser()).choices

    for subcommand in subcommands:
        assert f"sase artifact {subcommand}" in docs


def test_entry_dispatches_artifact_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_handle(args: argparse.Namespace) -> None:
        seen["command"] = args.command
        raise SystemExit(0)

    monkeypatch.setattr(sys, "argv", ["sase", "artifact", "list", "-j"])
    monkeypatch.setattr(artifact_handler, "handle_artifact_command", fake_handle)

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    assert seen == {"command": "artifact"}


def test_missing_artifact_subcommand_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "Usage: sase artifact" in capsys.readouterr().out
