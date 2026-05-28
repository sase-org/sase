"""Argument parser definition for the ``sase plugin`` command group."""

from __future__ import annotations

import argparse


def register_plugin_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase plugin`` command group."""
    plugin_parser = subparsers.add_parser(
        "plugin",
        help="Inspect installed SASE plugins and chop scripts",
        description="Inspect installed SASE plugin entry points and AXE chop script availability.",
    )
    plugin_subparsers = plugin_parser.add_subparsers(
        dest="plugin_subcommand",
        help="Plugin subcommands",
        required=True,
    )

    list_parser = plugin_subparsers.add_parser(
        "list",
        help="List installed plugin entry points and chop scripts",
    )
    _add_common_flags(list_parser)

    doctor_parser = plugin_subparsers.add_parser(
        "doctor",
        help="Diagnose installed plugin and chop setup",
    )
    _add_common_flags(doctor_parser)


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show additional entry point and chop detail",
    )
