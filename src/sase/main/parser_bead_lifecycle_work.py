"""Launch argument parser definitions for bead subcommands."""

from __future__ import annotations

import argparse

__all__ = ["register_bead_onboard_parser", "register_bead_work_parser"]


def _queue_capacity_arg(value: str) -> int:
    from sase.xprompt.queue_directive import validate_queue_capacity

    try:
        return validate_queue_capacity(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def register_bead_onboard_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead onboard``."""
    subparsers.add_parser("onboard", help="Show quick-start guide")


def register_bead_work_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead work``."""
    parser = subparsers.add_parser(
        "work",
        help="Create or launch one or more epic plan or task bead targets",
        description=(
            "Launch one or more existing epic plan or standalone task beads, "
            "Markdown epic plans, or an ordered mix of both. Each target is "
            "processed completely before the next begins, and the command stops "
            "at the first error while preserving earlier side effects. An epic "
            "launch schedules its phase and land agents. A task launch starts "
            "one deterministic worker. A Markdown epic plan can also be "
            "validated, archived into the SDD store, compiled into a bead DAG, "
            "and launched. Plan-file launches are idempotent and resume from "
            "an existing bead_id link."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead work sase-64\n"
            "  sase bead work sase-task --yes\n"
            "  sase bead work sase-64 sase-task --yes\n"
            "  sase bead work ./epic_plan.md --dry-run\n"
            "  sase bead work ./epic_plan.md --parent sase-64.2 --yes\n"
            "  sase bead work ./epic_plan.md --parent top-level --yes\n"
            "  sase bead work ./epic_plan.md --wait sase-s7.2,bead=sase-64.3 --yes\n"
            "  sase bead work ./epic_plan.md --yes\n"
            "  sase bead work ./epic_plan.md sase-task --yes\n"
            "  sase bead work ./epic_plan.md ./followup_plan.md --yes-to-all\n"
            "  sase bead work ./epic_plan.md --yes-to-all\n"
            "  sase bead work ./epic_plan.md --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="+",
        metavar="TARGET",
        help=(
            "One or more full or shorthand epic/task bead IDs or paths to "
            "validated epic plan files, processed in order"
        ),
    )
    parser.add_argument(
        "-a",
        "--artifacts-dir",
        metavar="DIR",
        help="Planner artifacts directory to back-fill after an approved epic launch",
    )
    parser.add_argument(
        "-c",
        "--capacity",
        metavar="N",
        type=_queue_capacity_arg,
        help=(
            "Epic targets only: per-launch weighted-load capacity budget. "
            "Omit for default queue behavior; use 1 to run alone. "
            "A segment whose xprompt claims more weight gets a budget "
            "equal to that weight. N must be at least 1."
        ),
    )
    parser.add_argument(
        "-C",
        "--cl-name",
        metavar="NAME",
        help="Patch name for the approved epic completion notification",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help=(
            "Validate and preview the wave plan without changing files, "
            "beads, or agents"
        ),
    )
    parser.add_argument(
        "--expect-prompt-snapshot",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help=(
            "Print one machine-readable result object per processed target; "
            "multi-target output is JSON Lines; implies --yes-to-all, so no "
            "confirmation prompt is shown"
        ),
    )
    parser.add_argument(
        "--launch-feedback",
        metavar="TEXT",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="Commit plan or bead state locally but skip post-commit pushes",
    )
    parser.add_argument(
        "-p",
        "--parent",
        metavar="ID|top-level",
        help=(
            "Override a plan file's parent_bead with a full or shorthand ID; "
            "use 'top-level' to create an unparented epic"
        ),
    )
    parser.add_argument(
        "-w",
        "--wait",
        metavar="SPEC",
        help=(
            "Comma-separated agent names and bead=<id> entries the launched "
            "phases wait for"
        ),
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip only the launch confirmation prompt",
    )
    parser.add_argument(
        "-Y",
        "--yes-to-all",
        action="store_true",
        help="Skip both destructive-cleanup and launch confirmation prompts",
    )
