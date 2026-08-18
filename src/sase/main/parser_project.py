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
        help="Allow disabling a project that still has live work",
    )


def register_project_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase project`` subcommand parser."""
    project_parser = subparsers.add_parser(
        "project",
        help="Inspect and mutate project lifecycle state",
        description=(
            "Inspect project lifecycle state and the current project. "
            "Running `sase project` defaults to `sase project list`."
        ),
    )
    project_sub = project_parser.add_subparsers(
        dest="project_subcommand",
        help="Project subcommands",
        metavar="{alias,current,disable,enable,list,set-state,show}",
    )

    alias_parser = project_sub.add_parser(
        "alias",
        help="Inspect and mutate project aliases",
    )
    alias_sub = alias_parser.add_subparsers(
        dest="alias_subcommand",
        help="Project alias subcommands",
        metavar="{add,clear,list,remove}",
    )
    alias_add_parser = alias_sub.add_parser(
        "add",
        help="Add an alias to a project",
    )
    alias_add_parser.add_argument("project", help="Project name")
    alias_add_parser.add_argument("alias", help="Alias name")
    alias_clear_parser = alias_sub.add_parser(
        "clear",
        help="Remove all aliases from a project",
    )
    alias_clear_parser.add_argument("project", help="Project name")
    alias_list_parser = alias_sub.add_parser(
        "list",
        help="List project aliases",
    )
    alias_list_parser.add_argument(
        "project",
        nargs="?",
        help="Optional project name to inspect",
    )
    alias_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    alias_parser.set_defaults(alias_subcommand="list", project=None, json=False)
    alias_remove_parser = alias_sub.add_parser(
        "remove",
        help="Remove an alias from a project",
    )
    alias_remove_parser.add_argument("project", help="Project name")
    alias_remove_parser.add_argument("alias", help="Alias name")

    current_parser = project_sub.add_parser(
        "current",
        help="Show the current project derived from the VCS xprompt MRU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print the current project: the first VCS xprompt MRU entry that "
            "resolves to an enabled SASE project.\n\n"
            "The current project is a pure read of the VCS xprompt MRU store "
            "(~/.sase/vcs_xprompt_mru.json). Launch an agent on a project, or "
            "on a Patch owned by that project, to make it current. There is "
            "no separate set command.\n\n"
            "Human output colors the project name with that project's accent "
            "and reports the canonical directory key, the origin (project or "
            "patch, naming the Patch when applicable), and the MRU ref that "
            "produced it. When nothing resolves, the command explains how to "
            "set a current project and exits 0."
        ),
        epilog=("examples:\n  sase project current\n  sase project current --json"),
    )
    current_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    for command, help_text in (
        ("disable", "Disable a project"),
        ("enable", "Enable a project"),
        ("activate", argparse.SUPPRESS),
        ("archive", argparse.SUPPRESS),
        ("close", argparse.SUPPRESS),
        ("deactivate", argparse.SUPPRESS),
    ):
        lifecycle_parser = project_sub.add_parser(
            command,
            help=help_text,
        )
        lifecycle_parser.add_argument("project", help="Project name")
        _add_force(lifecycle_parser)

    list_parser = project_sub.add_parser(
        "list",
        help="List SASE projects by lifecycle state",
    )
    list_parser.add_argument(
        "-s",
        "--state",
        default="enabled",
        metavar="{enabled,disabled,sibling,all}",
        help="Lifecycle state to include (default: enabled)",
    )
    list_parser.add_argument(
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
