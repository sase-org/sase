"""Parser tests for the ``sase tmux-agent`` command."""

from __future__ import annotations

import argparse

import pytest

from sase.main.parser import create_parser, default_list_delegation_notice
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    flat_help,
    parse_and_capture_help,
    walk_subparser_actions,
)


def _parser() -> argparse.ArgumentParser:
    return create_parser(only="tmux-agent")


def test_bare_invocation_is_not_delegated_to_a_list_subcommand() -> None:
    args = _parser().parse_args(["tmux-agent"])

    assert args.command == "tmux-agent"
    assert args.provider is None
    assert args.list is False
    assert default_list_delegation_notice(args) is None


def test_tmux_agent_has_no_list_child() -> None:
    parser = create_parser()
    tmux_paths = [
        path
        for path, action in walk_subparser_actions(parser)
        if path[:2] == ("sase", "tmux-agent")
    ]

    assert tmux_paths == []


def test_parser_accepts_every_public_form() -> None:
    short = _parser().parse_args(
        [
            "tmux-agent",
            "claude",
            "-c",
            "/tmp/proj",
            "-e",
            "max",
            "-j",
            "-l",
            "-n",
            "-r",
            "-s",
            "-v",
        ]
    )
    long = _parser().parse_args(
        [
            "tmux-agent",
            "claude",
            "--dir",
            "/tmp/proj",
            "--effort",
            "max",
            "--json",
            "--list",
            "--dry-run",
            "--refresh",
            "--safe",
            "--verbose",
        ]
    )

    for args in (short, long):
        assert args.provider == "claude"
        assert args.directory == "/tmp/proj"
        assert args.effort == "max"
        assert args.json is True
        assert args.list is True
        assert args.dry_run is True
        assert args.refresh is True
        assert args.safe is True
        assert args.verbose is True
        assert args.renumber is False


def test_renumber_is_an_internal_flag() -> None:
    args = _parser().parse_args(["tmux-agent", "--renumber"])
    help_text = flat_help(_parser().format_help())

    assert args.renumber is True
    assert "--renumber" not in help_text


def test_invalid_effort_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parser().parse_args(["tmux-agent", "--effort", "ludicrous"])

    assert exc_info.value.code == 2


def test_help_documents_the_menu_and_has_no_list_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = parse_and_capture_help(["tmux-agent", "-h"], capsys)
    flattened = flat_help(help_text)

    assert "There is no `list` subcommand" in flattened
    assert "paint the tmux Agent menu" in flattened
    assert "sase tmux-agent claude" in flattened
    assert "sase tmux-agent --list" in flattened
    assert "sase tmux-agent claude --dry-run" in flattened
    assert 'bind A run "sase tmux-agent"' in flattened
    assert "-l, --list" in flattened
    assert_metavar_option_documented(flattened, "-c", "--dir", "<dir>")
    assert_metavar_option_documented(flattened, "-e", "--effort", "<level>")
