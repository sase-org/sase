"""Argument parser for ``sase bead task-type``."""

from __future__ import annotations

import argparse


def register_bead_task_type_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead task-type``."""

    parser = subparsers.add_parser(
        "task-type",
        help="Inspect the effective task-type catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the effective task-type catalog assembled from builtins, "
            "plugins, and project config. Invoking 'sase bead task-type' "
            "without a subcommand delegates to 'sase bead task-type list'."
        ),
        epilog=(
            "examples:\n"
            "  sase bead task-type\n"
            "  sase bead task-type list\n"
            "  sase bead task-type list -a\n"
            "  sase bead task-type list -j\n"
            "  sase bead task-type show flake\n"
            "  sase bead task-type show flake -j"
        ),
    )
    task_type_sub = parser.add_subparsers(
        dest="task_type_subcommand",
        help="Task-type subcommands",
        metavar="{list,show}",
    )

    list_parser = task_type_sub.add_parser(
        "list",
        help="List task types agents may file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List the effective task-type catalog as a colored table of slug, "
            "label, summary, source, and whether agents may file each type. "
            "Agent-uncreatable types are hidden unless -a/--all is passed."
        ),
        epilog=(
            "examples:\n"
            "  sase bead task-type list\n"
            "  sase bead task-type list -a\n"
            "  sase bead task-type list -j"
        ),
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include agent-uncreatable types",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    show_parser = task_type_sub.add_parser(
        "show",
        help="Show one task type's fields, template, and provenance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show one task type: label, summary, when_to_use, every field "
            "with type, requirement, role, help, and validators, the body "
            "template, the triage threshold, and provenance. Reads are not "
            "audited; there is no -r/--reason."
        ),
        epilog=(
            "examples:\n"
            "  sase bead task-type show flake\n"
            "  sase bead task-type show flake -j"
        ),
    )
    show_parser.add_argument(
        "slug",
        metavar="<slug>",
        help="Task-type slug to inspect",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )


__all__ = ["register_bead_task_type_parser"]
