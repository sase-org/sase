"""Tests for CLI parser help rendering."""

from __future__ import annotations

import argparse

from sase.main.parser import create_parser


def _walk_subparser_actions(
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
            actions.extend(_walk_subparser_actions(child_parser, (*path, name)))
    return actions


def _parser_for(path: tuple[str, ...]) -> argparse.ArgumentParser:
    parser = create_parser()
    for command in path[1:]:
        subparser_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        parser = subparser_action.choices[command]
    return parser


def _help_subcommand_rows(help_text: str, expected_commands: set[str]) -> list[str]:
    commands: list[str] = []
    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        command = stripped.split(maxsplit=1)[0]
        if command in expected_commands:
            commands.append(command)
    return commands


def test_all_subparser_choices_are_sorted() -> None:
    """Every subcommand group keeps usage metavars sorted alphabetically."""
    parser = create_parser()

    for path, action in _walk_subparser_actions(parser):
        commands = list(action.choices)

        assert commands == sorted(commands), " ".join(path)


def test_all_visible_subparser_help_entries_are_sorted() -> None:
    """Every subcommand group renders its help rows sorted alphabetically."""
    parser = create_parser()

    for path, action in _walk_subparser_actions(parser):
        visible_commands = [
            choice_action.dest for choice_action in action._choices_actions
        ]

        assert visible_commands == sorted(visible_commands), " ".join(path)


def test_agents_help_renders_sorted_subcommands() -> None:
    """A formerly unsorted help view renders its user-facing rows sorted."""
    agents_parser = _parser_for(("sase", "agents"))
    expected_commands = {"archive", "index", "kill", "show", "status", "tag"}

    help_commands = _help_subcommand_rows(
        agents_parser.format_help(), expected_commands
    )

    assert help_commands == sorted(expected_commands)
    assert "{archive,index,kill,show,status,tag}" in agents_parser.format_help()
