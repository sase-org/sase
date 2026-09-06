"""Parser tests for ``sase migrate backup`` and ``sase migrate restore``."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import (
    compact_common_commands,
    parse_and_capture_help,
    root_subparser_action,
)


def test_migrate_is_registered_in_the_full_parser() -> None:
    parser = create_parser(only="migrate")

    args = parser.parse_args(["migrate", "backup", "/tmp/example"])

    assert args.command == "migrate"
    assert args.migrate_subcommand == "backup"
    assert args.root == "/tmp/example"
    assert args.apply is False
    assert args.json is False
    assert args.secondary is None


def test_migrate_is_not_a_compact_root_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = parse_and_capture_help(["--help"], capsys)
    assert "migrate" not in compact_common_commands(help_text)


def test_backup_apply_and_secondary_options() -> None:
    parser = create_parser(only="migrate")

    args = parser.parse_args(
        ["migrate", "backup", "/tmp/example", "-a", "-j", "-s", "/tmp/secondary"]
    )

    assert args.apply is True
    assert args.json is True
    assert args.secondary == "/tmp/secondary"


def test_restore_parses_backup_id_and_options() -> None:
    parser = create_parser(only="migrate")

    args = parser.parse_args(
        ["migrate", "restore", "athena-20260905T000000-abc123", "-a", "-j"]
    )

    assert args.migrate_subcommand == "restore"
    assert args.backup_id == "athena-20260905T000000-abc123"
    assert args.apply is True
    assert args.json is True
    assert args.root is None


def test_restore_accepts_root_override() -> None:
    parser = create_parser(only="migrate")

    args = parser.parse_args(
        ["migrate", "restore", "backup-id", "-r", "/tmp/live-root"]
    )

    assert args.root == "/tmp/live-root"


def test_bare_migrate_parses_with_no_subcommand_selected() -> None:
    """Neither ``backup`` nor ``restore`` is required at the argparse level.

    The handler prints usage and exits 1 for a bare invocation; ``kit-driver``
    later adds a ``list`` child that ``_default_list_subcommands()`` wires as
    the bare default, matching every other command group's convention.
    """
    parser = create_parser(only="migrate")

    args = parser.parse_args(["migrate"])

    assert args.migrate_subcommand is None


def test_migrate_subcommand_options_are_never_required() -> None:
    parser = create_parser(only="migrate")
    migrate_action = root_subparser_action(parser)
    migrate_parser = migrate_action.choices["migrate"]
    migrate_sub_action = next(
        action
        for action in migrate_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    for subcommand in ("backup", "restore"):
        sub_parser = migrate_sub_action.choices[subcommand]
        for action in sub_parser._actions:
            if action.option_strings:
                assert action.required is False, (subcommand, action.option_strings)
