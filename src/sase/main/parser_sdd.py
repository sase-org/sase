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
            "  sase sdd list --kind epics  # tier filter over plans/\n"
            "  sase sdd validate --show-warnings"
        ),
    )
    sdd_sub = sdd_parser.add_subparsers(dest="sdd_subcommand", help="SDD subcommands")

    init_parser = sdd_sub.add_parser(
        "init",
        help="Materialize provider storage and refresh generated guides",
        description=(
            "Materialize provider storage and refresh generated guides. "
            "Creating a missing GitHub companion always requires an "
            "interactive, default-no y/yes confirmation."
        ),
    )
    init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report provider and generated-file work without writing files",
    )
    init_parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        help="Show full file diffs for planned SDD changes",
    )
    add_sdd_path_arg(init_parser)

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
        choices=("prompts", "plans", "tales", "epics", "all"),
        default="all",
        help="Artifact kind; tales/epics filter plans by tier (default: all)",
    )
    list_parser.add_argument(
        "-j", "--json", action="store_true", help="Emit machine-readable JSON"
    )

    path_parser = sdd_sub.add_parser(
        "path",
        help="Print the effective SDD root or one canonical child directory",
        description=(
            "Print the effective SDD root for the current workspace. When kind "
            "is provided, print the directory that stores that logical kind. "
            "Resolution is read-only unless --ensure is passed."
        ),
    )
    path_parser.add_argument(
        "-e",
        "--ensure",
        action="store_true",
        help="Materialize and synchronize the backing companion clone",
    )
    path_parser.add_argument(
        "kind",
        nargs="?",
        choices=SDD_CANONICAL_DIRS,
        help="Canonical SDD kind to resolve",
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
        help="SDD root or project root path (default: current project)",
    )
