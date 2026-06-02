"""Argument parser definition for the ``sase project`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.core.project_lifecycle_wire import PROJECT_LIFECYCLE_STATES

_STATE_METAVAR = "{" + ",".join(PROJECT_LIFECYCLE_STATES) + "}"


def _add_force(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow deactivating a project that still has live work",
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
        metavar="{activate,deactivate,list,set-state,show}",
    )

    list_parser = project_sub.add_parser(
        "list",
        help="List SASE projects by lifecycle state",
    )
    list_parser.add_argument(
        "-s",
        "--state",
        default="active",
        metavar="{active,inactive,all}",
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
        metavar=_STATE_METAVAR,
        help="Target lifecycle state",
    )
    _add_force(set_state_parser)

    for command, help_text in (
        ("activate", "Set a project's lifecycle state to active"),
        ("deactivate", "Set a project's lifecycle state to inactive"),
        ("archive", argparse.SUPPRESS),
        ("close", argparse.SUPPRESS),
    ):
        alias_parser = project_sub.add_parser(
            command,
            help=help_text,
        )
        alias_parser.add_argument("project", help="Project name")
        _add_force(alias_parser)
