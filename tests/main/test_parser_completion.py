"""Tests for the ``sase completion`` argument parser."""

from __future__ import annotations

from sase.main.parser import create_parser, default_list_delegation_notice
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.parser_help_helpers import (
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_completion_group_defaults_to_list() -> None:
    parser = create_parser()
    omitted = parser.parse_args(["completion"])
    explicit = parser.parse_args(["completion", "list"])

    assert omitted.completion_subcommand == "list"
    assert omitted.json is False
    assert default_list_delegation_notice(omitted) == (
        "No subcommand provided for 'sase completion'; "
        "delegating to 'sase completion list'."
    )
    assert default_list_delegation_notice(explicit) is None


def test_completion_help_lists_sorted_subcommands() -> None:
    help_text = parser_for(("sase", "completion")).format_help()
    expected = {"bash", "candidates", "fish", "install", "list", "spec", "zsh"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{bash,candidates,fish,install,list,spec,zsh}" in help_text
    assert "defaults to `sase completion list`" in help_text
    assert 'eval "$(sase completion zsh)"' in help_text


def test_completion_spec_and_shells_accept_output() -> None:
    spec = parse_sase_args(["completion", "spec", "-j", "-o", "out.json"])
    bash = parse_sase_args(["completion", "bash", "--output", "out.bash"])
    fish = parse_sase_args(["completion", "fish", "-o", "out.fish"])
    zsh = parse_sase_args(["completion", "zsh", "--output", "out.zsh"])

    assert spec.command == "completion"
    assert spec.completion_subcommand == "spec"
    assert spec.json is True
    assert spec.output == "out.json"
    assert bash.completion_subcommand == "bash"
    assert bash.output == "out.bash"
    assert fish.completion_subcommand == "fish"
    assert fish.output == "out.fish"
    assert zsh.completion_subcommand == "zsh"
    assert zsh.output == "out.zsh"


def test_completion_install_accepts_shell_and_modifiers() -> None:
    detected = parse_sase_args(["completion", "install"])
    zsh = parse_sase_args(
        ["completion", "install", "zsh", "-d", "-f", "-t", "~/.zfunc"]
    )

    assert detected.completion_subcommand == "install"
    assert detected.shell is None
    assert detected.dry_run is False
    assert detected.force is False
    assert detected.target is None
    assert zsh.shell == "zsh"
    assert zsh.dry_run is True
    assert zsh.force is True
    assert zsh.target == "~/.zfunc"


def test_completion_child_help_documents_short_aliases() -> None:
    list_help = flat_help(parser_for(("sase", "completion", "list")).format_help())
    spec_help = flat_help(parser_for(("sase", "completion", "spec")).format_help())
    bash_help = flat_help(parser_for(("sase", "completion", "bash")).format_help())
    fish_help = flat_help(parser_for(("sase", "completion", "fish")).format_help())
    zsh_help = flat_help(parser_for(("sase", "completion", "zsh")).format_help())
    install_help = flat_help(
        parser_for(("sase", "completion", "install")).format_help()
    )

    assert "-j, --json" in list_help
    assert "-j, --json" in spec_help
    assert "-o, --output FILE" in spec_help
    assert "-o, --output FILE" in bash_help
    assert "-o, --output FILE" in fish_help
    assert "-o, --output FILE" in zsh_help
    assert "-d, --dry-run" in install_help
    assert "-f, --force" in install_help
    assert "-t, --target DIR" in install_help
    assert "complete -o default" in bash_help
    assert "__sase_cmd" in fish_help
    assert "fpath" in zsh_help
    assert "#compdef" in zsh_help
    assert "compinit" in install_help
