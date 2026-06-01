"""Argument parser definition for the ``sase project`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.core.project_lifecycle_wire import PROJECT_LIFECYCLE_STATES

_STATE_CHOICES = (*PROJECT_LIFECYCLE_STATES, "all")


def _add_force(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow archiving or closing a project that still has live work",
    )


def register_project_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase project`` subcommand parser."""
    project_parser = subparsers.add_parser(
        "project",
        help="Inspect and mutate project lifecycle state",
    )
    project_sub = project_parser.add_subparsers(
        dest="project_subcommand",
        help="Project subcommands",
    )

    list_parser = project_sub.add_parser(
        "list",
        help="List SASE projects by lifecycle state",
    )
    list_parser.add_argument(
        "-s",
        "--state",
        choices=_STATE_CHOICES,
        default="active",
        help="Lifecycle state to include (default: active)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    show_parser = project_sub.add_parser(
        "show",
        help="Show one project's lifecycle record",
    )
    show_parser.add_argument("project", help="Project name")
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    set_state_parser = project_sub.add_parser(
        "set-state",
        help="Set a project's lifecycle state",
    )
    set_state_parser.add_argument("project", help="Project name")
    set_state_parser.add_argument(
        "state",
        choices=PROJECT_LIFECYCLE_STATES,
        help="Target lifecycle state",
    )
    _add_force(set_state_parser)

    for command, state in (
        ("activate", "active"),
        ("archive", "archived"),
        ("close", "closed"),
    ):
        alias_parser = project_sub.add_parser(
            command,
            help=f"Set a project's lifecycle state to {state}",
        )
        alias_parser.add_argument("project", help="Project name")
        _add_force(alias_parser)
