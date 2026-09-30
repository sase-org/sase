"""State-change argument parser definitions for bead subcommands."""

from __future__ import annotations

import argparse

from sase.cli_file_values import AT_PATH_PREFIX
from sase.completion.compat import set_completion_compat_option_strings
from sase.main._parser_bead_lifecycle_shared import AT_PATH_READS_IT

__all__ = [
    "register_bead_close_parser",
    "register_bead_create_parser",
    "register_bead_open_parser",
    "register_bead_rm_parser",
    "register_bead_snooze_parser",
    "register_bead_update_parser",
]


def register_bead_close_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead close``."""
    parser = subparsers.add_parser(
        "close",
        help="Close one or more issues",
        description=(
            "Close one or more issues atomically. With --phases, the single "
            "target is an epic whose numbered phase beads are closed instead. "
            "Full IDs can route to another enabled project's owning store; "
            "mixed-store close batches are rejected before mutation. "
            f"Free-text values accept {AT_PATH_PREFIX}<path>."
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
        help=(
            "Append this attributed note to each issue before closing it; "
            f"{AT_PATH_READS_IT}"
        ),
    )
    parser.add_argument(
        "-S",
        "--allow-sensitive",
        dest="allow_sensitive",
        action="store_true",
        help=("Attach files from sensitive paths"),
    )
    parser.add_argument(
        "-L",
        "--local-only",
        dest="local_only",
        action="store_true",
        help=("Keep new attachments on this machine without uploading"),
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
    parser.add_argument(
        "-r",
        "--reason",
        help=f"Close reason; {AT_PATH_READS_IT}",
    )
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
            "require an explicit size and -T 'task(<slug>)'; plan beads reject "
            "size, while raw phase creation accepts it optionally. Every "
            "create requires -w/--reason explaining why the bead was filed. "
            "Typed tasks take repeatable -f/--field values for the type's "
            "declared fields. A full parent ID in plan(...,<parent>) or "
            "phase(<parent>) creates the child in that parent's owning "
            "enabled project. "
            f"Free-text values accept {AT_PATH_PREFIX}<path>."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead create -T 'task(bug)' -t \"Fix retry race\" -z medium "
            "-w 'A second agent reproduced dropped retries after the queue change' "
            "-d @/tmp/diagnosis.md -f location=src/retry.py "
            "-f repro='fails on retry'\n"
            "  sase bead create -T 'task(bug)' -t \"Fix retry race\" -z medium "
            "-w 'A second agent reproduced dropped retries after the queue change' "
            "-f location=src/retry.py -f repro='fails on retry'\n"
            "  sase bead create -T 'task(flake)' -t \"Flaky retry\" -z medium "
            "-w 'CI flakes on the retry path three times this week' "
            "-f node_id=tests/foo.py::test_bar -f evidence=@notes.txt\n"
            '  sase bead create -T phase(sase-ab) -t "Add endpoint" -z small '
            "-w 'Epic plan calls for the endpoint in this phase'\n"
            "  sase bead create -T plan(plan:202608/feature.md) "
            "-t \"Feature\" -r epic -w 'Planning the feature breakdown'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-a", "--assignee", help="Assignee")
    parser.add_argument(
        "-b",
        "--bug-id",
        help="Bug ID to pass when creating the attached Patch",
    )
    patch_option = parser.add_argument(
        "-c",
        "--patch",
        "--changespec",
        dest="patch",
        help="Attach a Patch name to a plan bead",
    )
    set_completion_compat_option_strings(patch_option, "--changespec")
    parser.add_argument(
        "-d",
        "--description",
        help=f"Issue description; {AT_PATH_READS_IT}",
    )
    parser.add_argument(
        "-x",
        "--external-ref",
        help="Project-qualified external issue identity, e.g. bug:sase#42",
    )
    parser.add_argument(
        "-f",
        "--field",
        action="append",
        metavar="K=V",
        help=(
            "Task-type field value (repeatable). A value of @<path> is read "
            "from that file"
        ),
    )
    parser.add_argument(
        "-m",
        "--model",
        help=(
            "Model to use when this bead is launched. Provider-qualified "
            "(e.g. codex/gpt-6-sol) or local alias (e.g. #pro). For epic "
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
        help="Phase/task size; read sase/memory/sase_sizes.md for guidance",
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
            "phase(<parent_id>), or "
            "task(<slug>); parent IDs may be full or shorthand. New tasks "
            "require a catalog slug; list them with `sase bead task-type`"
        ),
    )
    parser.add_argument(
        "-w",
        "--reason",
        required=True,
        help=(
            "Why this bead was filed (one or two sentences, not the title); "
            f"{AT_PATH_READS_IT}. Required; blank or over-2000-character "
            "reasons are rejected before mutation. Example: -w 'A second "
            "agent reproduced dropped retries after the queue change'"
        ),
    )


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
        help=f"Why this task is being deferred; {AT_PATH_READS_IT}",
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
    parser.add_argument(
        "-d",
        "--description",
        help=f"Issue description; {AT_PATH_READS_IT}",
    )
    external_ref_group = parser.add_mutually_exclusive_group()
    external_ref_group.add_argument(
        "-x",
        "--external-ref",
        help="Project-qualified external issue identity, e.g. bug:sase#42",
    )
    external_ref_group.add_argument(
        "-X",
        "--clear-external-ref",
        action="store_true",
        help="Clear the external issue identity",
    )
    parser.add_argument(
        "-m",
        "--model",
        help=(
            "Model for this bead's launch. Provider-qualified (e.g. "
            "codex/gpt-6-sol) or local alias (e.g. #pro). Pass '' to clear."
        ),
    )
    parser.add_argument(
        "--notes",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-n",
        "--note",
        help=(f"Append this attributed note to each issue; {AT_PATH_READS_IT}"),
    )
    parser.add_argument(
        "-S",
        "--allow-sensitive",
        dest="allow_sensitive",
        action="store_true",
        help=("Attach files from sensitive paths"),
    )
    parser.add_argument(
        "-L",
        "--local-only",
        dest="local_only",
        action="store_true",
        help=("Keep new attachments on this machine without uploading"),
    )
    parser.add_argument(
        "-b",
        "--remove-by",
        metavar="DATE/RELEASE",
        help=(
            "Extend a flag bead's removal thresholds, e.g. 2026-12-01/0.19.0; "
            "takes exactly one flag bead ID"
        ),
    )
    parser.add_argument(
        "-z",
        "--size",
        choices=["xsmall", "small", "medium", "large", "xlarge"],
        help="Phase size; read sase/memory/sase_sizes.md for guidance",
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
    parser.add_argument(
        "-T",
        "--task-type",
        dest="task_type",
        metavar="SLUG",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("-t", "--title")
