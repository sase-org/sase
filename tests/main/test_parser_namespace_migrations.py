"""Tests for parser namespace compatibility boundaries."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import root_subparser_action


def test_axe_stop_force_parser_aliases() -> None:
    long_args = create_parser().parse_args(["axe", "stop", "--force"])
    short_args = create_parser().parse_args(["axe", "stop", "-f"])

    assert long_args.axe_subcommand == "stop"
    assert long_args.force is True
    assert short_args.force is True


def test_init_namespace_parses_migrated_leaf_commands() -> None:
    """The init namespace parses its migrated leaf commands."""
    parser = create_parser()

    memory_args = parser.parse_args(["init", "memory"])
    assert memory_args.command == "init"
    assert memory_args.init_subcommand == "memory"
    assert memory_args.no_commit is False

    memory_no_commit_args = parser.parse_args(["init", "memory", "--no-commit"])
    assert memory_no_commit_args.command == "init"
    assert memory_no_commit_args.init_subcommand == "memory"
    assert memory_no_commit_args.no_commit is True

    repo_args = parser.parse_args(["init", "repo", "--no-commit"])
    assert repo_args.command == "init"
    assert repo_args.init_subcommand == "repo"
    assert repo_args.no_commit is True

    init_args = parser.parse_args(
        ["init", "skills", "--dry-run", "--provider", "codex"]
    )
    assert init_args.command == "init"
    assert init_args.init_subcommand == "skills"
    assert init_args.dry_run is True
    assert init_args.provider == "codex"


def test_git_namespace_is_not_public_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bare-git project creation is internal to #git reference resolution."""
    parser = create_parser()
    root_subparsers = root_subparser_action(parser)

    assert "git" not in root_subparsers.choices

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["git", "init", "demo"])

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "invalid choice" in stderr
    assert "git" in stderr


def test_legacy_init_commands_are_rejected() -> None:
    """The migrated legacy top-level commands are no longer accepted."""
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["init-skills", "--dry-run"])

    with pytest.raises(SystemExit):
        parser.parse_args(["init-git", "demo"])
