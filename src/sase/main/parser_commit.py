"""Argument parser definitions for commit-lifecycle CLI subcommands."""

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from sase.commit_methods import METHOD_ALIASES, VALID_METHODS

_REMOVED_FILE_FLAG_MESSAGE = (
    "error: `-f/--file` was removed. `sase stitch create` now stages every change in\n"
    "the repository, including untracked files. Use `-x/--exclude PATH` (repeatable)\n"
    "to leave a path out of the commit."
)


class _RemovedFileFlagAction(argparse.Action):
    """Reject the removed ``-f/--file`` flag with an actionable exit-1 message.

    Generated skill copies are deployed to a global chezmoi destination and can
    lag the in-repo sources, so a stale copy may still pass ``-f``. Exiting 1
    here (instead of letting argparse's ``unrecognized arguments`` exit 2)
    avoids being mistaken for a paused-rebase conflict by the commit skill.
    """

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(option_strings, dest, nargs="?", **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        del parser, namespace, values, option_string
        print(_REMOVED_FILE_FLAG_MESSAGE, file=sys.stderr)
        sys.exit(1)


def add_commit_create_options(parser: argparse.ArgumentParser) -> None:
    """Add the shared commit/proposal/PR dispatch flags to *parser*.

    Shared by the top-level ``sase commit`` legacy alias and the canonical
    ``sase stitch create`` subcommand so the two spellings cannot drift.
    """
    msg_group = parser.add_mutually_exclusive_group()
    msg_group.add_argument(
        "-m",
        "--message",
        help="Commit message string",
    )
    msg_group.add_argument(
        "-M",
        "--message-file",
        help="Path to file containing the commit message / PR description",
    )
    parser.add_argument(
        "-f",
        "--file",
        action=_RemovedFileFlagAction,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=[],
        dest="exclude",
        metavar="PATH",
        help="Repo-relative file or directory to leave out of the commit (repeatable)",
    )
    parser.add_argument(
        "--only-file",
        action="append",
        default=[],
        dest="only_files",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-n",
        "--name",
        help="Branch/Patch name (required for create_pull_request)",
    )
    parser.add_argument(
        "-b",
        "--bug-id",
        type=int,
        default=0,
        help="Bug ID to associate with the commit (overrides $SASE_BUG_ID)",
    )
    parser.add_argument(
        "-B",
        "--do-not-close-bead",
        action="store_true",
        dest="do_not_close_bead",
        help="Do not auto-close the assigned in-progress task bead after commit",
    )
    parser.add_argument(
        "-c",
        "--checkout-target",
        default="HEAD~1",
        help="Branch point for create_pull_request (default: HEAD~1)",
    )
    parser.add_argument(
        "-p",
        "--parent",
        help="Parent Patch name (overrides auto-detection from current branch)",
    )
    parser.add_argument(
        "-s",
        "--status",
        type=str.lower,
        choices=["wip", "draft", "ready"],
        help="Patch status (overrides $SASE_PR_STATUS; default: draft)",
    )
    parser.add_argument(
        "-t",
        "--type",
        dest="method",
        choices=[*VALID_METHODS, *METHOD_ALIASES],
        help="Commit method (default: $SASE_COMMIT_METHOD or create_commit)",
    )
    parser.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help=(
            "Resume a previously-checkpointed commit after manual conflict "
            "resolution. When set, -m/-M/-x and other commit args are ignored."
        ),
    )


def register_commit_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'commit' subcommand parser."""
    commit_parser = subparsers.add_parser(
        "commit",
        help="Dispatch a VCS commit operation (legacy alias for `sase stitch create`)",
    )
    add_commit_create_options(commit_parser)


def register_restore_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'restore' subcommand parser."""
    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore a reverted Patch by re-applying its diff and creating a new PR",
    )
    restore_parser.add_argument(
        "name",
        nargs="?",
        help="NAME of the reverted Patch to restore (e.g., 'foobar_feature__2')",
    )
    # Options for 'restore' (keep sorted alphabetically by long option name)
    restore_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all reverted Patches",
    )


def register_revert_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'revert' subcommand parser."""
    revert_parser = subparsers.add_parser(
        "revert",
        help="Revert a Patch by pruning its PR and archiving the diff",
    )
    revert_parser.add_argument(
        "name",
        help="NAME of the Patch to revert",
    )
