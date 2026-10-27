"""Argument parser definition for the ``sase footprint`` command group."""

from __future__ import annotations

import argparse

from sase.footprint.ids import NAMESPACES

_FORMAT_CHOICES = ("rich", "json", "markdown")

_FOOTPRINT_SUMMARY = "Show the local usage census of sase surfaces."
_FOOTPRINT_DESCRIPTION = (
    "Footprint keeps a local, privacy-by-construction census of which "
    "sase surfaces (CLI commands and options, TUI actions and keys, views "
    "and modals, macros, skills, config leaves, automation) are used, and "
    "joins it with a generated feature catalog. Use `sase footprint mode off` "
    "to stop recording. Bare `sase footprint` shows this help."
)


def register_footprint_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase footprint`` group and its implemented views."""
    footprint_parser = subparsers.add_parser(
        "footprint",
        help=_FOOTPRINT_SUMMARY,
        description=_FOOTPRINT_DESCRIPTION,
    )
    footprint_sub = footprint_parser.add_subparsers(
        dest="footprint_subcommand",
        help="Footprint views",
        metavar="{catalog,mode}",
    )
    _register_catalog_parser(footprint_sub)
    _register_mode_parser(footprint_sub)


def _register_mode_parser(footprint_sub: argparse._SubParsersAction) -> None:
    mode_parser = footprint_sub.add_parser(
        "mode",
        help="Show or set local Footprint recording",
        description=(
            "Show the effective Footprint recording mode, or set it to `off` "
            "or `local`. Recording is local and stores no command arguments."
        ),
    )
    mode_parser.add_argument(
        "mode",
        nargs="?",
        choices=("local", "off"),
        help="Recording mode (default: show the current mode)",
    )


def _register_catalog_parser(
    footprint_sub: argparse._SubParsersAction,
) -> None:
    catalog_parser = footprint_sub.add_parser(
        "catalog",
        help="List the generated feature catalog",
        description=(
            "List the generated Footprint feature catalog: every "
            "allowlisted feature ID sase knows, grouped by area. The file "
            "lives at src/sase/footprint/catalog.jsonl and is regenerated "
            "by `just fix`."
        ),
        epilog=(
            "examples:\n"
            "  sase footprint catalog\n"
            "  sase footprint catalog -n cli -f json\n"
            "  sase footprint catalog -A cli.bead -f markdown"
        ),
    )
    catalog_parser.add_argument(
        "-A",
        "--area",
        default=None,
        metavar="AREA",
        help="Show only one area (for example cli.bead)",
    )
    catalog_parser.add_argument(
        "-f",
        "--format",
        choices=_FORMAT_CHOICES,
        default="rich",
        help="Output format (default: rich)",
    )
    catalog_parser.add_argument(
        "-n",
        "--namespace",
        choices=NAMESPACES,
        default=None,
        metavar="NS",
        help="Show only one namespace (for example cli)",
    )


__all__ = ["register_footprint_parser"]
