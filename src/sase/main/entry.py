"""Main entry point for the SASE CLI tool."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from sase.footprint._cli import CliHit


def main() -> NoReturn:
    """Main entry point for the SASE CLI tool."""
    from sase.footprint._cli import begin

    hit = begin()
    outcome: int | BaseException = 0
    try:
        _main(hit)
    except BaseException as exc:
        outcome = exc
        raise
    finally:
        hit.record(outcome)


def _main(hit: CliHit) -> NoReturn:
    """Dispatch one invocation; the public ``main`` owns the recorder finally."""
    hit.mark_parse_stage()
    if len(sys.argv) > 1 and sys.argv[1].startswith("-"):
        from .global_options import consume_global_options

        consume_global_options(print_command_header=True)

    from sase.legacy_xprompt_syntax import normalize_legacy_root_args

    normalize_legacy_root_args()

    if len(sys.argv) >= 2 and sys.argv[1] == "bead":
        from .bead_fast_path import try_handle_bead_fast_path

        words = _bead_feature_path(sys.argv[2:])
        hit.set_path(words)
        exit_code = try_handle_bead_fast_path(sys.argv[2:])
        if exit_code is not None:
            sys.exit(exit_code)

    if len(sys.argv) >= 2 and sys.argv[1] == "goal":
        from .goal_fast_path import try_handle_goal_fast_path

        hit.set_path(["goal"])
        exit_code = try_handle_goal_fast_path(sys.argv[2:])
        if exit_code is not None:
            argv = sys.argv[2:]
            if argv and not argv[0].startswith("-"):
                hit.set_path(["goal", argv[0]])
            sys.exit(exit_code)

    if sys.argv[1:3] == ["completion", "candidates"]:
        from .completion_fast_path import try_handle_completion_candidates

        hit.set_path(["completion", "candidates"])
        exit_code = try_handle_completion_candidates(sys.argv[3:])
        if exit_code is not None:
            sys.exit(exit_code)

    if sys.argv[1:3] == ["completion", "ensure"]:
        from .completion_fast_path import try_handle_completion_ensure

        hit.set_path(["completion", "ensure"])
        exit_code = try_handle_completion_ensure(sys.argv[3:])
        if exit_code is not None:
            sys.exit(exit_code)

    # Check for 'sase run' special cases before argparse processes it
    # This allows us to handle queries that contain spaces
    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        from .query_handler import handle_run_special_cases

        hit.set_path(["run"])
        args_after_run = sys.argv[2:]
        handle_run_special_cases(args_after_run)
        # If we get here, no special case was handled, continue to argparse

    # Plugin-mounted top-level commands (e.g. `sase listen`) dispatch here so
    # an unknown root word never pays for a full argparse build. Built-in
    # words fall through untouched.
    if len(sys.argv) >= 2:
        from sase.plugin_commands.dispatch import try_handle_plugin_command

        plugin_word = sys.argv[1]
        exit_code = try_handle_plugin_command(sys.argv[1:])
        if exit_code is not None:
            hit.set_plugin(plugin_word)
            sys.exit(exit_code)

    from .parser import (
        create_parser,
        default_list_delegation_notice,
        parser_only_hint,
    )

    parser = create_parser(only=parser_only_hint(sys.argv))
    from sase.footprint._cli import set_parser_path

    set_parser_path(hit, parser, sys.argv[1:])
    args = parser.parse_args()

    # Announce when a bare command group was implicitly delegated to its `list`
    # child, so the delegation starts the command output.
    delegation_notice = default_list_delegation_notice(args)
    if delegation_notice is not None:
        print(delegation_notice)

    from ._dispatch_initial import dispatch_initial_commands

    dispatch_initial_commands(args, parser)

    from ._dispatch_remaining import dispatch_remaining_commands

    dispatch_remaining_commands(args)
    print(f"Unknown command: {args.command}")
    sys.exit(1)


def _bead_feature_path(argv: list[str]) -> list[str]:
    """Return only bead parser words, excluding every user-supplied value."""
    if not argv or argv[0].startswith("-"):
        return ["bead"]
    words = ["bead", argv[0]]
    if argv[0] in {"dep", "ref"} and len(argv) > 1:
        allowed = (
            {"add", "list", "rm", "tree"} if argv[0] == "dep" else {"add", "list", "rm"}
        )
        if argv[1] in allowed:
            words.append(argv[1])
    return words


if __name__ == "__main__":
    main()
