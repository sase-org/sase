"""Argument parser definition for the ``sase disk`` command group."""

from __future__ import annotations

import argparse


def register_disk_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase disk`` subcommand parser."""

    disk_parser = subparsers.add_parser(
        "disk",
        help="Inspect and reclaim SASE-owned disk usage",
        description=(
            "Inspect SASE-owned disk usage and delegate cleanup to each owner.\n\n"
            "Bare `sase disk` defaults to `sase disk list`."
        ),
    )
    disk_subparsers = disk_parser.add_subparsers(
        dest="disk_subcommand",
        help="Disk subcommands",
        metavar="{list,reap}",
    )

    list_parser = disk_subparsers.add_parser(
        "list",
        help="List SASE disk usage by owner",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )

    reap_parser = disk_subparsers.add_parser(
        "reap",
        help="Preview or run owner cleanup passes",
        description=(
            "Delegate cleanup to the owner for each disk class. This command is "
            "a dry run unless --apply is passed; unowned Cargo-shaped strays are "
            "reported by `sase disk list` and are never deleted here."
        ),
    )
    reap_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Run owner cleanup passes instead of previewing them",
    )
    reap_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    reap_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Limit project-scoped artifact and workspace cleanup to one project",
    )


__all__ = ["register_disk_parser"]
