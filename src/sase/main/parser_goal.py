"""Argument parser definition for the ``sase goal`` CLI subcommand."""

from __future__ import annotations

import argparse

_GOAL_SUBCOMMANDS = "{doctor,drop,edit,list,merge,new,reopen,show}"
_GOAL_STATUSES = "{unsettled,active,review,done,dropped,settled,all}"


def register_goal_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase goal`` subcommand parser."""
    goal_parser = subparsers.add_parser(
        "goal",
        help="Create, list, and reshape durable goal records",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create, list, show, edit, drop, reopen, merge, and check "
            "durable goal records.\n"
            "\n"
            "With no subcommand, `sase goal` defaults to `sase goal list`.\n"
            "\n"
            "`new`, `edit`, `drop`, `reopen`, `merge`, and `doctor --repair` "
            "are human verbs: they refuse inside agent runs. Agents may run "
            "`sase goal list` and `sase goal show`."
        ),
        epilog=(
            "examples:\n"
            "  sase goal                         # same as `sase goal list`\n"
            "  sase goal list -s done            # history scan, newest first\n"
            "  sase goal show 7k2mq             # the goal card\n"
            '  sase goal new -t "Try goals" -o "I can see this goal '
            'from apollo"\n'
            '  sase goal edit 7k2mq -o "New outcome"\n'
            '  sase goal drop 7k2mq -w "tried it"\n'
            '  sase goal reopen 7k2mq -m "trying again"\n'
            '  sase goal merge 3fq9t -i 7k2mq -w "same work"\n'
            "  sase goal doctor                  # check the ledger\n"
            "  sase goal list -j                 # GoalListWire JSON"
        ),
    )
    goal_sub = goal_parser.add_subparsers(
        dest="goal_subcommand",
        help="Goal subcommands",
        metavar=_GOAL_SUBCOMMANDS,
    )

    doctor = goal_sub.add_parser(
        "doctor",
        help="Check the goal ledger, optionally repairing markers",
    )
    doctor.add_argument(
        "-j", "--json", action="store_true", help="Print the doctor report"
    )
    doctor.add_argument(
        "-r",
        "--repair",
        action="store_true",
        help="Repair markers and rebuild the projection (human only)",
    )

    drop = goal_sub.add_parser("drop", help="Settle a goal as canceled")
    drop.add_argument("goal_id", metavar="ID", help="Goal id or ref")
    drop.add_argument("-w", "--why", required=True, help="Why the goal is dropped")

    edit = goal_sub.add_parser("edit", help="Edit a goal's content")
    edit.add_argument("goal_id", metavar="ID", help="Goal id or ref")
    edit.add_argument(
        "-c",
        "--criterion",
        action="append",
        default=None,
        help="Add an acceptance criterion (repeatable)",
    )
    edit.add_argument("-o", "--outcome", help="Replacement outcome")
    edit.add_argument("-t", "--title", help="Replacement title")
    edit.add_argument(
        "-x",
        "--remove-criterion",
        action="append",
        default=None,
        help="Remove a criterion by id (repeatable)",
    )

    goal_list = goal_sub.add_parser(
        "list",
        help="List goals (defaults to unsettled)",
    )
    goal_list.add_argument(
        "-a",
        "--all-projects",
        action="store_true",
        help="Render one section per enabled project",
    )
    goal_list.add_argument(
        "-f",
        "--fresh",
        action="store_true",
        help="Integrate synchronously before reading",
    )
    goal_list.add_argument(
        "-j", "--json", action="store_true", help="Print GoalListWire JSON"
    )
    goal_list.add_argument(
        "-n", "--limit", type=int, default=None, help="Maximum goals shown"
    )
    goal_list.add_argument(
        "-s",
        "--status",
        default="unsettled",
        help=(
            "Status filter (default: unsettled). done, dropped, settled, "
            "and all scan history, newest first"
        ),
    )

    merge = goal_sub.add_parser("merge", help="Merge one goal into another")
    merge.add_argument("goal_id", metavar="ID", help="Source goal id or ref")
    merge.add_argument("-i", "--into", required=True, help="Target goal id or ref")
    merge.add_argument("-w", "--why", default=None, help="Why the goals merge")

    new = goal_sub.add_parser("new", help="Create a goal")
    new.add_argument("-o", "--outcome", required=True, help="Goal outcome")
    new.add_argument("-t", "--title", required=True, help="Goal title")
    new.add_argument(
        "-c",
        "--criterion",
        action="append",
        default=None,
        help="Acceptance criterion (repeatable)",
    )

    reopen = goal_sub.add_parser("reopen", help="Reopen a settled goal")
    reopen.add_argument("goal_id", metavar="ID", help="Goal id or ref")
    reopen.add_argument("-m", "--message", required=True, help="Why the goal reopens")

    show = goal_sub.add_parser("show", help="Show one goal card")
    show.add_argument("goal_id", metavar="ID", help="Goal id or ref")
    show.add_argument(
        "-j", "--json", action="store_true", help="Print GoalStateWire JSON"
    )


__all__ = ["register_goal_parser"]
