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

    # sase memory init
    memory_subparsers.add_parser(
        "init", help="Initialize the memory repository at ~/.sase/memory/"
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

    # sase memory show
    show_parser = memory_subparsers.add_parser("show", help="Display a memory file")
    show_parser.add_argument("name", help="Name of the memory to show")
    show_parser.add_argument(
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

    # sase memory rm
    rm_parser = memory_subparsers.add_parser("rm", help="Remove a memory file")
    rm_parser.add_argument("name", help="Name of the memory to remove")
    rm_parser.add_argument(
        "-p",
        "--project",
        help="Project name (default: auto-detect from CWD)",
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
