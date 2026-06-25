"""Argument parser definition for the ``sase plugin`` CLI subcommand."""

from __future__ import annotations

import argparse


def _add_load_flags(parser: argparse.ArgumentParser) -> None:
    """Add the cache/refresh and JSON flags shared by plugin subcommands."""
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass the cache and refetch the catalog from GitHub",
    )


def register_plugin_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase plugin`` subcommand parser."""
    plugin_parser = subparsers.add_parser(
        "plugin",
        help="Discover SASE plugins from the GitHub catalog",
        description=(
            "Discover every SASE plugin that exists by treating the GitHub "
            "`sase-plugin` topic as the canonical registry. Running `sase plugin` "
            "with no subcommand delegates to `sase plugin list`."
        ),
    )
    plugin_sub = plugin_parser.add_subparsers(
        dest="plugin_subcommand",
        help="Plugin subcommands",
        metavar="{list,show}",
    )

    list_parser = plugin_sub.add_parser(
        "list",
        help="List all known SASE plugins (built-in and community)",
    )
    _add_load_flags(list_parser)
    list_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show extra columns: stars, last updated, and the full topic list",
    )

    show_parser = plugin_sub.add_parser(
        "show",
        help="Show detailed information about a single SASE plugin",
    )
    show_parser.add_argument(
        "plugin_name",
        metavar="<plugin_name>",
        help="Plugin name to show (short name, repo, or owner/repo full name)",
    )
    _add_load_flags(show_parser)
