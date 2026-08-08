"""Lifecycle argument parser definitions for bead subcommands."""

from __future__ import annotations

import argparse


def register_bead_plus_one_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead +1``."""
    parser = subparsers.add_parser(
        "+1",
        help="Corroborate an existing task with independent evidence",
        description=(
            "Record one independently attributed report on an existing task bead. "
            "Each reporter counts at most once; later details belong in `sase bead "
            "note`. Draft and closed tasks are promoted to ready."
        ),
        epilog=(
            "Examples:\n"
            '  sase bead +1 sase-ab -n "Reproduced on Linux with v0.14.0"\n'
            '  sase bead +1 ab -n "Trace confirms the same failure" '
            "-R research:202608/trace.txt\n"
            '  sase bead +1 sase-ab -a agent.two -n "Independent reproduction"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("id", help="Full or shorthand task bead ID")
    parser.add_argument(
        "-a",
        "--author",
        metavar="NAME",
        help="Reporter recorded on the evidence (default: current agent, else owner)",
    )
    parser.add_argument(
        "-n",
        "--note",
        required=True,
        metavar="TEXT",
        help="Required independent reproduction or impact evidence",
    )
    parser.add_argument(
        "-R",
        "--ref",
        action="append",
        help="Artifact reference supporting the evidence (repeatable)",
    )


def register_bead_close_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead close``."""
    parser = subparsers.add_parser(
        "close",
        help="Close one or more issues",
        description=(
            "Close one or more issues atomically. With --phases, the single "
            "target is an epic whose numbered phase beads are closed instead."
        ),
        epilog=(
            "Examples:\n"
            '  sase bead close sase-at.1 --note "verified with just check"\n'
            "  sase bead close sase-at -p 1,2,3\n"
            "  sase bead close sase-at -p 1-3\n"
            '  sase bead close sase-at -p 1-3,5 --reason "phases landed together"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ids",
        nargs="+",
        metavar="ID",
        help=(
            "Full or shorthand issue IDs to close "
            "(exactly one epic ID when --phases is used)"
        ),
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help=(
            "Close unfinished descendants; requires --reason and a "
            "non-done --resolution"
        ),
    )
    parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="Commit the close locally but skip the post-commit push",
    )
    parser.add_argument(
        "-n",
        "--note",
        help="Append this attributed note to each issue before closing it",
    )
    parser.add_argument(
        "-p",
        "--phases",
        action="append",
        metavar="SPEC",
        help=(
            "Close these phase beads of the target epic; comma-separated "
            "numbers and ranges (e.g. 1,3,5-7)"
        ),
    )
    parser.add_argument("-r", "--reason", help="Close reason")
    parser.add_argument(
        "-R",
        "--resolution",
        choices=["canceled", "done", "superseded"],
        default=None,
        help=(
            "How this bead was resolved; a real close defaults to done, while "
            "an already-closed bead is not compared unless this is supplied"
        ),
    )


def register_bead_create_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead create``."""
    parser = subparsers.add_parser(
        "create",
        help="Create a new issue",
        description=(
            "Create a plan, phase, or standalone task bead. New task beads "
            "require an explicit size; plan beads reject size, while raw phase "
            "creation accepts it optionally."
        ),
        epilog=(
            "Examples:\n"
            '  sase bead create -T task -t "Fix retry race" -z medium\n'
            '  sase bead create -T phase(sase-ab) -t "Add endpoint" -z small\n'
            "  sase bead create -T plan(plans:202608/feature.md) "
            '-t "Feature" -r epic'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-a", "--assignee", help="Assignee")
    parser.add_argument(
        "-b",
        "--bug-id",
        help="Bug ID to pass when creating the attached ChangeSpec",
    )
    parser.add_argument(
        "-c", "--changespec", help="Attach a ChangeSpec name to a plan bead"
    )
    parser.add_argument("-d", "--description", help="Issue description")
    parser.add_argument(
        "-m",
        "--model",
        help=(
            "Model to use when this bead is launched. Provider-qualified "
            "(e.g. codex/gpt-5.6-sol) or local alias (e.g. #pro). For epic "
            "plan beads this becomes the land-agent model; for phase beads it "
            "is the per-phase work model; for task beads it is the task-worker "
            "model."
        ),
    )
    parser.add_argument(
        "-R",
        "--ref",
        action="append",
        help="Artifact reference to attach (repeatable)",
    )
    parser.add_argument(
        "-z",
        "--size",
        choices=["xsmall", "small", "medium", "large", "xlarge"],
        help="Phase/task size controlling plan-first prompting and model routing",
    )
    parser.add_argument(
        "-r",
        "--tier",
        choices=["plan", "epic"],
        help="Plan-bead tier (plan or epic)",
    )
    parser.add_argument("-t", "--title", required=True, help="Issue title")
    parser.add_argument(
        "-T",
        "--type",
        required=True,
        help=(
            "Bead type: plan(<plan_file>), plan(<plan_file>,<parent_id>), "
            "phase(<parent_id>), or task; parent IDs may be full or shorthand"
        ),
    )


def register_bead_note_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead note``."""
    parser = subparsers.add_parser("note", help="Append an attributed note entry")
    parser.add_argument("id", help="Full or shorthand issue ID")
    parser.add_argument(
        "text",
        nargs="+",
        help="Note text to append",
    )
    parser.add_argument(
        "-a",
        "--author",
        metavar="NAME",
        help="Author recorded on the entry (default: current agent, else store owner)",
    )


def register_bead_onboard_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead onboard``."""
    subparsers.add_parser("onboard", help="Show quick-start guide")


def register_bead_open_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead open``."""
    parser = subparsers.add_parser("open", help="Reopen an issue")
    parser.add_argument("id", help="Full or shorthand issue ID to reopen")


def register_bead_rm_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead rm``."""
    parser = subparsers.add_parser("rm", help="Remove issues and all their children")
    parser.add_argument(
        "ids",
        nargs="+",
        metavar="ids",
        help="One or more full or shorthand issue IDs to remove",
    )


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
        "--cl-name",
        metavar="NAME",
        help="ChangeSpec name for the approved epic completion notification",
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


def register_bead_snooze_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead snooze``."""
    parser = subparsers.add_parser(
        "snooze",
        help="Defer a task bead until a wake time or a +1 threshold",
        description=(
            "Defer one or more open or ready task beads. A snoozed task keeps "
            "its place in every listing but stops raising triage gates until "
            "its wake time arrives or its +1 target is reached, whichever "
            "comes first. Use --cancel to wake one early."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead snooze sase-ab -u 3d\n"
            '  sase bead snooze sase-ab -u 2h -r "waiting on the upstream fix"\n'
            "  sase bead snooze sase-ab -u 7d -p 2\n"
            "  sase bead snooze sase-ab -u 2026-08-09T09:00:00-04:00\n"
            "  sase bead snooze sase-ab sase-cd --cancel"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ids",
        nargs="+",
        metavar="ID",
        help="One or more full or shorthand task bead IDs to snooze",
    )
    parser.add_argument(
        "-c",
        "--cancel",
        action="store_true",
        help="Wake these beads now, returning them to ready",
    )
    parser.add_argument(
        "-p",
        "--plus-ones",
        type=int,
        metavar="COUNT",
        help="Also wake when this many additional +1 reports arrive",
    )
    parser.add_argument(
        "-r",
        "--reason",
        metavar="TEXT",
        help="Why this task is being deferred",
    )
    parser.add_argument(
        "-u",
        "--until",
        metavar="TIME",
        help=(
            "Wake time: a duration (30m, 2h, 1h30m, 3d, 1d12h) or an absolute "
            "ISO-8601 timestamp; required unless --cancel is given"
        ),
    )


def register_bead_update_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead update``."""
    parser = subparsers.add_parser(
        "update",
        help="Update one or more issues",
        description=(
            "Update one or more issues. Every listed bead receives the same "
            "field changes in a single atomic commit."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead update sase-at.1 -s in_progress\n"
            "  sase bead update at.1 at.2 at.3 -s ready\n"
            "  sase bead update sase-at.1 sase-at.2 -a alice -z medium"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ids",
        nargs="+",
        metavar="ID",
        help="One or more full or shorthand issue IDs to update",
    )
    parser.add_argument("-a", "--assignee")
    parser.add_argument("-D", "--design")
    parser.add_argument("-d", "--description")
    parser.add_argument(
        "-m",
        "--model",
        help=(
            "Model for this bead's launch. Provider-qualified (e.g. "
            "codex/gpt-5.6-sol) or local alias (e.g. #pro). Pass '' to clear."
        ),
    )
    parser.add_argument("-n", "--notes")
    parser.add_argument(
        "-z",
        "--size",
        choices=["xsmall", "small", "medium", "large", "xlarge"],
        help="Phase size controlling plan-first prompting and default model routing",
    )
    parser.add_argument(
        "-s",
        "--status",
        choices=["open", "claimed", "ready", "in_progress", "closed"],
        help=(
            "New status; `snoozed` is absent on purpose because it needs a "
            "wake time — use `sase bead snooze <id> -u <time>`"
        ),
    )
    parser.add_argument("-r", "--tier", choices=["plan", "epic"])
    parser.add_argument("-t", "--title")
