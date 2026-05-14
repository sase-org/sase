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
    expected_commands = {"archive", "index", "kill", "names", "show", "status", "tag"}

    help_commands = _help_subcommand_rows(
        agents_parser.format_help(), expected_commands
    )

    assert help_commands == sorted(expected_commands)
    assert "{archive,index,kill,names,show,status,tag}" in agents_parser.format_help()


def test_daemon_help_keeps_recovery_commands_discoverable() -> None:
    """Daemon help exposes the user-facing recovery command sequence."""
    daemon_parser = _parser_for(("sase", "daemon"))
    help_text = daemon_parser.format_help()
    expected_commands = {
        "backup",
        "checkpoint",
        "diff",
        "doctor",
        "list-backups",
        "rebuild",
        "restore",
        "scheduler",
        "start",
        "status",
        "stop",
        "verify",
    }

    help_commands = _help_subcommand_rows(help_text, expected_commands)

    assert help_commands == sorted(expected_commands)
    assert "sase daemon doctor" in help_text
    assert "sase daemon verify --surface all" in help_text
    assert "sase daemon rebuild --surface all" in help_text
    assert "SASE_NO_DAEMON=1" in help_text


def test_daemon_subcommand_help_names_runtime_scope() -> None:
    """Recovery subcommand help states what is runtime-only."""
    doctor_help = _parser_for(("sase", "daemon", "doctor")).format_help()
    rebuild_help = _parser_for(("sase", "daemon", "rebuild")).format_help()
    restore_help = _parser_for(("sase", "daemon", "restore")).format_help()

    assert "--repair-stale-lock" in doctor_help
    assert "sase daemon doctor --json" in doctor_help
    assert "--reset-storage" in rebuild_help
    assert "Source files, JSONL stores, artifacts, and repos are not deleted" in (
        rebuild_help
    )
    assert "projection-only" in restore_help
    assert "does not edit source stores" in restore_help
