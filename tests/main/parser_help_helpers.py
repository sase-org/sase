"""Shared helpers for CLI parser help tests."""

from __future__ import annotations

import argparse
import re
from io import StringIO

import pytest

from sase.main.parser import create_parser


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def walk_subparser_actions(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ("sase",)
) -> list[tuple[tuple[str, ...], argparse._SubParsersAction]]:
    actions: list[tuple[tuple[str, ...], argparse._SubParsersAction]] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue

        actions.append((path, action))
        seen_child_parsers: set[int] = set()
        for name, child_parser in action.choices.items():
            child_id = id(child_parser)
            if child_id in seen_child_parsers:
                continue
            seen_child_parsers.add(child_id)
            actions.extend(walk_subparser_actions(child_parser, (*path, name)))
    return actions


def parser_for(path: tuple[str, ...]) -> argparse.ArgumentParser:
    parser = create_parser()
    for command in path[1:]:
        subparser_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        parser = subparser_action.choices[command]
    return parser


def help_subcommand_rows(help_text: str, expected_commands: set[str]) -> list[str]:
    commands: list[str] = []
    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(?P<command>\S+)(?: \((?P<aliases>[^)]+)\))?", stripped)
        if match is None:
            continue
        command = match.group("command")
        if command in expected_commands:
            commands.append(command)
        aliases = match.group("aliases")
        if aliases is not None:
            commands.extend(
                alias.strip()
                for alias in aliases.split(",")
                if alias.strip() in expected_commands
            )
    return commands


def flat_help(help_text: str) -> str:
    return " ".join(help_text.split())


def root_subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def parse_and_capture_help(args: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(args)

    assert exc_info.value.code == 0
    return capsys.readouterr().out


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def compact_common_command_rows(help_text: str) -> list[str]:
    commands: list[str] = []
    in_common_commands = False
    for line in help_text.splitlines():
        if line == "Common commands:":
            in_common_commands = True
            continue
        if in_common_commands and not line:
            break
        if in_common_commands:
            commands.append(line.split(maxsplit=1)[0])
    return commands


def compact_common_commands(help_text: str) -> set[str]:
    return set(compact_common_command_rows(help_text))
