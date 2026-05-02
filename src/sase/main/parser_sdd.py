"""Argument parser definition for the ``sase sdd`` command group."""

from __future__ import annotations

import argparse


def register_sdd_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'sdd' command parser."""
    sdd_parser = subparsers.add_parser(
        "sdd",
        help="Initialize, validate, list, and repair SDD prompt/plan metadata",
    )
    sdd_sub = sdd_parser.add_subparsers(dest="sdd_subcommand", help="SDD subcommands")

    init_parser = sdd_sub.add_parser(
        "init",
        help="Create or refresh sdd/README.md",
    )
    _add_path_arg(init_parser)

    validate_parser = sdd_sub.add_parser(
        "validate",
        help="Validate SDD frontmatter links",
    )
    _add_path_arg(validate_parser)
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

    links_parser = sdd_sub.add_parser(
        "links",
        help="List SDD frontmatter links",
    )
    _add_path_arg(links_parser)
    links_parser.add_argument(
        "-j", "--json", action="store_true", help="Emit machine-readable JSON"
    )

    list_parser = sdd_sub.add_parser(
        "list",
        help="List SDD markdown files",
    )
    _add_path_arg(list_parser)
    list_parser.add_argument(
        "-k",
        "--kind",
        choices=("prompts", "tales", "epics", "legends", "all"),
        default="all",
        help="File kind to list (default: all)",
    )
    list_parser.add_argument(
        "-j", "--json", action="store_true", help="Emit machine-readable JSON"
    )

    repair_parser = sdd_sub.add_parser(
        "repair-links",
        help="Infer and repair bidirectional SDD links",
    )
    _add_path_arg(repair_parser)
    repair_parser.add_argument(
        "-w", "--write", action="store_true", help="Write inferred link fixes"
    )


def _add_path_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--path",
        default=None,
        help="SDD root or project root path (default: ./sdd or ./.sase/sdd)",
    )
