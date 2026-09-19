"""Tests for the ``sase agent hold`` argument parser."""

from __future__ import annotations

import argparse

from sase.main.parser_agent_hold import register_agent_hold_parser


def _build() -> argparse._SubParsersAction:
    parser = argparse.ArgumentParser(prog="sase agent")
    agents_sub = parser.add_subparsers(dest="agent_subcommand")
    register_agent_hold_parser(agents_sub)
    return agents_sub


def _hold_subparsers(
    agents_sub: argparse._SubParsersAction,
) -> argparse._SubParsersAction:
    hold_parser = agents_sub.choices["hold"]
    return next(
        action
        for action in hold_parser._subparsers._group_actions  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction)
    )


def test_hold_subcommands_are_alphabetically_ordered() -> None:
    hold_sub = _hold_subparsers(_build())
    assert list(hold_sub.choices) == ["create", "list", "release", "run", "show"]


def test_every_public_hold_option_has_a_short_and_long_alias() -> None:
    hold_sub = _hold_subparsers(_build())
    for name, subparser in hold_sub.choices.items():
        for action in subparser._actions:  # noqa: SLF001
            if not action.option_strings or action.dest == "help":
                continue
            short = [s for s in action.option_strings if len(s) == 2]
            long_forms = [s for s in action.option_strings if s.startswith("--")]
            assert short, f"{name}: {action.option_strings} has no short alias"
            assert long_forms, f"{name}: {action.option_strings} has no long form"


def test_create_accepts_positional_name_and_tribe_selectors() -> None:
    hold_sub = _hold_subparsers(_build())
    args = hold_sub.choices["create"].parse_args(["team", "@ops", "-f"])
    assert args.selectors == ["team", "@ops"]
    assert args.future is True
    assert args.names == []
    assert args.scope == "project"
    assert args.ttl is None


def test_create_flag_only_selectors_still_parse() -> None:
    hold_sub = _hold_subparsers(_build())
    args = hold_sub.choices["create"].parse_args(["-f"])
    assert args.future is True
    assert args.selectors == []
    assert args.names == []
    assert args.scope == "project"
    assert args.ttl is None


def test_pending_help_documents_proc_limitation() -> None:
    hold_sub = _hold_subparsers(_build())
    help_text = hold_sub.choices["create"].format_help()
    assert "does not capture undispatched procs" in " ".join(help_text.split())


def test_run_command_words_capture_everything_after_dashdash() -> None:
    hold_sub = _hold_subparsers(_build())
    args = hold_sub.choices["run"].parse_args(["-f", "--", "just", "check"])
    assert args.hold_run_command_words == ["--", "just", "check"]


def test_show_key_is_positional_and_optional_dash_k() -> None:
    hold_sub = _hold_subparsers(_build())
    empty = hold_sub.choices["show"].parse_args([])
    assert empty.armer_key is None
    assert empty.key is None
    positional = hold_sub.choices["show"].parse_args(["cli:review"])
    assert positional.armer_key == "cli:review"
    flagged = hold_sub.choices["show"].parse_args(["-k", "cli:review"])
    assert flagged.key == "cli:review"


def test_release_key_is_optional_positional_or_dash_k() -> None:
    hold_sub = _hold_subparsers(_build())
    args = hold_sub.choices["release"].parse_args([])
    assert args.key is None
    assert args.armer_key is None
    positional = hold_sub.choices["release"].parse_args(["cli:review"])
    assert positional.armer_key == "cli:review"
