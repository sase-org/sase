"""Argument parser definition for the 'agents' CLI subcommand."""

import argparse


def register_agents_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'agents' subcommand parser."""
    agents_parser = subparsers.add_parser(
        "agents",
        help="Inspect, show, and kill running agents across all projects",
    )
    agents_sub = agents_parser.add_subparsers(
        dest="agents_subcommand", help="Agents subcommands"
    )

    # sase agents status (default when no subcommand given)
    status_parser = agents_sub.add_parser(
        "status",
        help="List running agents (pretty table by default, JSON with -j)",
    )
    status_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help=(
            "Include recently-completed DONE/FAILED agents"
            " (capped at 50 most-recent per project)"
        ),
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    status_parser.add_argument(
        "-p",
        "--project",
        help="Only show agents for the given project name",
    )

    # sase agents kill -n NAME
    kill_parser = agents_sub.add_parser(
        "kill",
        help="SIGTERM a running agent by name",
    )
    kill_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to kill",
    )

    # sase agents show -n NAME
    show_parser = agents_sub.add_parser(
        "show",
        help="Render a full detail panel for one agent",
    )
    show_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to show",
    )

    # sase agents tag {add,remove,list}
    tag_parser = agents_sub.add_parser(
        "tag",
        help="Manage user-defined tags on agents (used by the Agents tab)",
    )
    tag_sub = tag_parser.add_subparsers(dest="tag_subcommand", help="Tag subcommands")

    tag_add_parser = tag_sub.add_parser(
        "add",
        help="Add one or more tags to an agent",
    )
    tag_add_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to tag",
    )
    tag_add_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        required=True,
        help="Tag name (without '@'); repeat -t to add several at once",
    )

    tag_remove_parser = tag_sub.add_parser(
        "remove",
        help="Remove one or more tags from an agent",
    )
    tag_remove_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to untag",
    )
    tag_remove_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        required=True,
        help="Tag name (without '@'); repeat -t to remove several at once",
    )

    tag_list_parser = tag_sub.add_parser(
        "list",
        help="Print tags as JSON (all agents, or filtered by --name)",
    )
    tag_list_parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Limit output to a single agent",
    )
