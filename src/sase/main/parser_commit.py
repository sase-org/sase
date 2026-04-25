"""Argument parser definitions for commit-lifecycle CLI subcommands."""

import argparse


def register_commit_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'commit' subcommand parser."""
    commit_parser = subparsers.add_parser(
        "commit",
        help="Dispatch a VCS commit operation",
    )
    msg_group = commit_parser.add_mutually_exclusive_group()
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
    commit_parser.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        dest="files",
        help="File to stage (repeat for multiple; omit to stage all changes)",
    )
    commit_parser.add_argument(
        "-n",
        "--name",
        help="Branch/CL name (required for create_pull_request)",
    )
    commit_parser.add_argument(
        "-b",
        "--bead-id",
        help="Bead ID to close and associate with the commit",
    )
    commit_parser.add_argument(
        "-B",
        "--bug-id",
        type=int,
        default=0,
        help="Bug ID to associate with the commit (overrides $SASE_BUG_ID)",
    )
    commit_parser.add_argument(
        "-c",
        "--checkout-target",
        default="HEAD~1",
        help="Branch point for create_pull_request (default: HEAD~1)",
    )
    commit_parser.add_argument(
        "-p",
        "--parent",
        help="Parent ChangeSpec name (overrides auto-detection from current branch)",
    )
    commit_parser.add_argument(
        "-s",
        "--status",
        type=str.lower,
        choices=["wip", "draft", "ready"],
        help="ChangeSpec status (overrides $SASE_PR_STATUS; default: draft)",
    )
    from sase.workflows.commit.workflow import METHOD_ALIASES, VALID_METHODS

    commit_parser.add_argument(
        "-t",
        "--type",
        dest="method",
        choices=[*VALID_METHODS, *METHOD_ALIASES],
        help="Commit method (default: $SASE_COMMIT_METHOD or create_commit)",
    )
    commit_parser.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help=(
            "Resume a previously-checkpointed commit after manual conflict "
            "resolution. When set, -m/-M/-f and other commit args are ignored."
        ),
    )


def register_restore_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'restore' subcommand parser."""
    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore a reverted ChangeSpec by re-applying its diff and creating a new CL",
    )
    restore_parser.add_argument(
        "name",
        nargs="?",
        help="NAME of the reverted ChangeSpec to restore (e.g., 'foobar_feature__2')",
    )
    # Options for 'restore' (keep sorted alphabetically by long option name)
    restore_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all reverted ChangeSpecs",
    )


def register_revert_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'revert' subcommand parser."""
    revert_parser = subparsers.add_parser(
        "revert",
        help="Revert a ChangeSpec by pruning its CL and archiving the diff",
    )
    revert_parser.add_argument(
        "name",
        help="NAME of the ChangeSpec to revert",
    )
