"""Argument parser definitions for the 'sase agent hold' subcommand group."""

from __future__ import annotations

import argparse

_HOLD_SUBCOMMAND_ORDER = ("create", "list", "release", "run", "show")


def register_agent_hold_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent hold' subcommand group."""
    hold_parser = agents_sub.add_parser(
        "hold",
        description=(
            "Create, inspect, release, and wrap durable admission holds. "
            "Running bare `sase agent hold` delegates to `sase agent hold list`."
        ),
        help=(
            "Arm and manage reverse-wait admission holds "
            "(blocks WAITING/QUEUED/future agents and undispatched procs)"
        ),
    )
    hold_sub = hold_parser.add_subparsers(
        dest="hold_subcommand",
        help="Hold subcommands",
    )

    _register_create_parser(hold_sub)
    _register_list_parser(hold_sub)
    _register_release_parser(hold_sub)
    _register_run_parser(hold_sub)
    _register_show_parser(hold_sub)
    _sort_hold_subcommands(hold_sub)


def _add_selector_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-n",
        "--name",
        dest="names",
        action="append",
        default=[],
        metavar="NAME",
        help="Block this exact agent name or proc shell name (repeatable)",
    )
    parser.add_argument(
        "-t",
        "--tribe",
        dest="tribes",
        action="append",
        default=[],
        metavar="TRIBE",
        help="Block agents in this tribe, with or without '@' (repeatable)",
    )
    parser.add_argument(
        "-H",
        "--hood",
        dest="hoods",
        action="append",
        default=[],
        metavar="HOOD",
        help="Block agents in this hood, without a --role suffix (repeatable)",
    )
    parser.add_argument(
        "-f",
        "--future",
        action="store_true",
        help="Block agents and undispatched procs submitted after this hold is armed",
    )
    parser.add_argument(
        "-p",
        "--pending",
        action="store_true",
        help=(
            "Freeze the WAITING/QUEUED agents in scope right now and block "
            "only those (does not capture undispatched procs or agents/procs "
            "launched later)"
        ),
    )


def _add_scope_and_ttl_arguments(
    parser: argparse.ArgumentParser, *, ttl_help: str
) -> None:
    parser.add_argument(
        "-s",
        "--scope",
        choices=("project", "host"),
        default="project",
        help="Limit the hold to the current project, or the whole host (default: project)",
    )
    parser.add_argument(
        "-T",
        "--ttl",
        default=None,
        metavar="DURATION",
        help=ttl_help,
    )


def _register_create_parser(hold_sub: argparse._SubParsersAction) -> None:
    create_parser = hold_sub.add_parser(
        "create",
        help="Arm a hold; requires at least one of -n/-t/-H/-f/-p",
    )
    _add_selector_arguments(create_parser)
    _add_scope_and_ttl_arguments(
        create_parser,
        ttl_help=(
            "Hold TTL: bare seconds or a duration like 90s / 45m / 2h "
            "(default: the configured agent_hold_default_ttl)"
        ),
    )


def _register_list_parser(hold_sub: argparse._SubParsersAction) -> None:
    list_parser = hold_sub.add_parser(
        "list",
        help="List active holds",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print a stable JSON array instead of a table",
    )


def _register_release_parser(hold_sub: argparse._SubParsersAction) -> None:
    release_parser = hold_sub.add_parser(
        "release",
        help="Release a hold (defaults to the current agent/session's own hold)",
    )
    release_parser.add_argument(
        "-k",
        "--key",
        default=None,
        metavar="ARMER_KEY",
        help="Armer key to release (default: the current agent/session's own hold)",
    )


def _register_show_parser(hold_sub: argparse._SubParsersAction) -> None:
    show_parser = hold_sub.add_parser(
        "show",
        help="Show full detail for one hold, including frozen pending artifact dirs",
    )
    show_parser.add_argument(
        "-k",
        "--key",
        required=True,
        metavar="ARMER_KEY",
        help="Armer key to show",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print the raw hold record as JSON instead of a detail panel",
    )


def _register_run_parser(hold_sub: argparse._SubParsersAction) -> None:
    run_parser = hold_sub.add_parser(
        "run",
        help="Arm a hold around a command, releasing it when the command exits",
        description=(
            "Arm a hold, run COMMAND, and release the hold in all cases -- "
            "success, failure, or interruption -- preserving COMMAND's exit "
            "status. With no selector flags, defaults to -f/--future plus "
            "-p/--pending (the documented selector-free quiesce recipe)."
        ),
    )
    _add_selector_arguments(run_parser)
    _add_scope_and_ttl_arguments(
        run_parser,
        ttl_help=(
            "Hold TTL ceiling while COMMAND runs: bare seconds or a duration "
            "like 90s / 45m / 2h (default: the configured agent_hold_default_ttl)"
        ),
    )
    run_parser.add_argument(
        "hold_run_command_words",
        nargs=argparse.REMAINDER,
        metavar="-- COMMAND",
        help="The command to run under the hold, introduced by --",
    )


def _sort_hold_subcommands(hold_sub: argparse._SubParsersAction) -> None:
    choices = hold_sub.choices
    ordered = {
        name: choices[name] for name in _HOLD_SUBCOMMAND_ORDER if name in choices
    }
    extras = {name: choices[name] for name in sorted(set(choices) - set(ordered))}
    choices.clear()
    choices.update(ordered)
    choices.update(extras)
    order = {name: index for index, name in enumerate(choices)}
    hold_sub._choices_actions.sort(  # noqa: SLF001 - argparse has no public sorter.
        key=lambda action: order.get(action.dest, len(order))
    )
