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


def test_create_requires_no_positional_target() -> None:
    hold_sub = _hold_subparsers(_build())
    args = hold_sub.choices["create"].parse_args(["-f"])
    assert args.future is True
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


def test_show_requires_key() -> None:
    hold_sub = _hold_subparsers(_build())
    try:
        hold_sub.choices["show"].parse_args([])
    except SystemExit as exc:
        assert exc.code != 0
    else:  # pragma: no cover - defensive
        raise AssertionError("show without -k should exit non-zero")


def test_release_key_is_optional() -> None:
    hold_sub = _hold_subparsers(_build())
    args = hold_sub.choices["release"].parse_args([])
    assert args.key is None
