"""Argument parser definition for the ``sase sdd`` command group."""

from __future__ import annotations

import argparse


def register_sdd_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'sdd' command parser."""
    from sase.sdd._paths import SDD_CANONICAL_DIRS

    sdd_parser = subparsers.add_parser(
        "sdd",
        help="Initialize, inspect, validate, list, and repair SDD metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Manage SDD prompt/artifact documentation and frontmatter links. "
            "With no subcommand, defaults to `sase sdd list`."
        ),
        epilog=(
            "examples:\n"
            "  sase sdd path\n"
            "  sase sdd path research\n"
            "  sase sdd list --kind epics\n"
            "  sase sdd validate --show-warnings"
        ),
    )
    sdd_sub = sdd_parser.add_subparsers(dest="sdd_subcommand", help="SDD subcommands")

    init_parser = sdd_sub.add_parser(
        "init",
        help="Write legacy SDD init config and refresh generated guides",
    )
    init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report SDD config and generated-file drift without writing files",
    )
    add_sdd_path_arg(init_parser)
    init_parser.add_argument(
        "-s",
        "--storage",
        choices=("auto", "in_tree", "local", "separate_repo"),
        default=None,
        help=(
            "Write an explicit sdd.storage value instead of the legacy "
            "version_controlled alias"
        ),
    )

    links_parser = sdd_sub.add_parser(
        "links",
        help="List SDD frontmatter links",
    )
    add_sdd_path_arg(links_parser)
    links_parser.add_argument(
        "-j", "--json", action="store_true", help="Emit machine-readable JSON"
    )

    list_parser = sdd_sub.add_parser(
        "list",
        help="List SDD markdown files",
    )
    add_sdd_path_arg(list_parser)
    list_parser.add_argument(
        "-k",
        "--kind",
        choices=("prompts", "tales", "epics", "legends", "myths", "all"),
        default="all",
        help="File kind to list (default: all)",
    )
    list_parser.add_argument(
        "-j", "--json", action="store_true", help="Emit machine-readable JSON"
    )

    migrate_parser = sdd_sub.add_parser(
        "migrate",
        help="Migrate SDD files to a provider companion repository",
        description=(
            "Migrate the current project's SDD files into the provider "
            "companion repository used by sdd.storage=separate_repo. Existing "
            "local .sase/sdd stores are connected to the companion remote; "
            "in-tree sdd/ files are copied into .sase/sdd first."
        ),
    )
    migrate_parser.add_argument(
        "-c",
        "--create",
        action="store_true",
        help="Create the missing companion repository before migrating",
    )
    migrate_parser.add_argument(
        "-p",
        "--path",
        default=None,
        help="Project root path to migrate (default: current directory)",
    )
    migrate_parser.add_argument(
        "-r",
        "--remove-in-tree",
        action="store_true",
        help="After migration, remove tracked in-tree sdd/ files in a separate commit",
    )

    path_parser = sdd_sub.add_parser(
        "path",
        help="Print the effective SDD root or one canonical child directory",
        description=(
            "Print the effective SDD root for the current workspace. When kind "
            "is provided, print that canonical child directory under the root. "
            "This uses the fast directory-only SDD resolver and does not "
            "materialize remote stores."
        ),
    )
    path_parser.add_argument(
        "kind",
        nargs="?",
        choices=SDD_CANONICAL_DIRS,
        help="Canonical SDD child directory to append",
    )

    repair_parser = sdd_sub.add_parser(
        "repair-links",
        help="Infer and repair bidirectional SDD links",
    )
    add_sdd_path_arg(repair_parser)
    repair_parser.add_argument(
        "-w", "--write", action="store_true", help="Write inferred link fixes"
    )

    validate_parser = sdd_sub.add_parser(
        "validate",
        help="Validate SDD frontmatter links",
    )
    add_sdd_path_arg(validate_parser)
    validate_parser.add_argument(
        "-j", "--json", action="store_true", help="Emit machine-readable JSON"
    )
    validate_parser.add_argument(
        "-q", "--quiet", action="store_true", help="Only print validation failures"
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat unpaired historical files as validation errors",
    )
    validate_parser.add_argument(
        "-W",
        "--show-warnings",
        action="store_true",
        help="Show warning-severity issues (hidden by default)",
    )


def add_sdd_path_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--path",
        default=None,
        help="SDD root or project root path (default: ./sdd or ./.sase/sdd)",
    )
