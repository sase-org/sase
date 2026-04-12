"""Argument parser for the 'sase memory' subcommand."""

import argparse


def register_memory_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'memory' subcommand parser."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Manage git-versioned agent memory",
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_subcommand", help="Memory subcommands"
    )

    # sase memory add
    add_parser = memory_subparsers.add_parser("add", help="Create a new memory file")
    add_parser.add_argument("name", help="Name of the memory")
    add_parser.add_argument(
        "-d",
        "--description",
        required=True,
        help="One-line description of the memory",
    )
    add_parser.add_argument(
        "-m",
        "--message",
        help="Inline content for the memory body (otherwise reads from stdin)",
    )
    add_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )
    add_parser.add_argument(
        "-s",
        "--system",
        action="store_true",
        help="Place in system/ directory (always loaded into prompts)",
    )
    add_parser.add_argument(
        "-t",
        "--type",
        required=True,
        dest="memory_type",
        choices=[
            "architecture",
            "convention",
            "decision",
            "feedback",
            "reference",
            "pitfall",
        ],
        help="Memory category type",
    )

    # sase memory bootstrap
    bootstrap_parser = memory_subparsers.add_parser(
        "bootstrap",
        help="Seed initial memory by exploring the codebase",
    )
    bootstrap_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )

    # sase memory defrag
    defrag_parser = memory_subparsers.add_parser(
        "defrag",
        help="Reorganize and consolidate memory files",
    )
    defrag_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )

    # sase memory init
    memory_subparsers.add_parser(
        "init", help="Initialize the memory repository at ~/.sase/memory/"
    )

    # sase memory inject
    inject_parser = memory_subparsers.add_parser(
        "inject", help="Output formatted memory content for prompt injection"
    )
    inject_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )

    # sase memory list
    list_parser = memory_subparsers.add_parser("list", help="List memories")
    list_parser.add_argument(
        "-p",
        "--project",
        help="Filter to a specific project (default: all)",
    )

    # sase memory reflect
    reflect_parser = memory_subparsers.add_parser(
        "reflect",
        help="Distill learnings from a recent session into memory",
    )
    reflect_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )

    # sase memory remote {add,rm}
    remote_parser = memory_subparsers.add_parser(
        "remote", help="Manage remotes for the memory repository"
    )
    remote_subparsers = remote_parser.add_subparsers(
        dest="remote_subcommand", help="Remote subcommands"
    )

    remote_add_parser = remote_subparsers.add_parser(
        "add", help="Configure a remote for the memory repository"
    )
    remote_add_parser.add_argument("url", help="Remote URL (e.g. git@github.com:...)")
    remote_add_parser.add_argument(
        "-n",
        "--name",
        default="origin",
        help="Remote name (default: origin)",
    )

    remote_rm_parser = remote_subparsers.add_parser(
        "rm", help="Remove a remote from the memory repository"
    )
    remote_rm_parser.add_argument(
        "-n",
        "--name",
        default="origin",
        help="Remote name to remove (default: origin)",
    )

    # sase memory rm
    rm_parser = memory_subparsers.add_parser("rm", help="Remove a memory file")
    rm_parser.add_argument("name", help="Name of the memory to remove")
    rm_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )

    # sase memory show
    show_parser = memory_subparsers.add_parser("show", help="Display a memory file")
    show_parser.add_argument("name", help="Name of the memory to show")
    show_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
    )

    # sase memory sync
    sync_parser = memory_subparsers.add_parser(
        "sync", help="Push/pull memory from configured remote"
    )
    sync_parser.add_argument(
        "-r",
        "--remote",
        default="origin",
        help="Remote name (default: origin)",
    )

    # sase memory tree
    tree_parser = memory_subparsers.add_parser(
        "tree", help="Show filetree of the memory repository"
    )
    tree_parser.add_argument(
        "-p",
        "--project",
        help="Filter to a specific project (default: show all)",
    )
