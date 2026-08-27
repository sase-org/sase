"""Argument parser definition for the ``sase pager`` command."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import wrap_width
from sase.markdown_width import markdown_print_width

COLOR_CHOICES = ("auto", "always", "never")
LINK_CHOICES = ("auto", "never")


def register_pager_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase pager`` top-level command."""
    pager_parser = subparsers.add_parser(
        "pager",
        help="Read refs, paths, or stdin in the SASE link-traversing pager",
        description=(
            "Open artifact references, file paths, or stdin as one navigable "
            "SASE pager document. With redirected stdout, --plain, or no "
            "controlling terminal, the command writes plain text instead of "
            "starting the Textual app."
        ),
    )
    pager_parser.add_argument(
        "inputs",
        nargs="*",
        metavar="REF|PATH",
        help=(
            "Artifact reference or file path to add as a section; omit or pass "
            "'-' by itself to read stdin"
        ),
    )
    pager_parser.add_argument(
        "-c",
        "--color",
        choices=COLOR_CHOICES,
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    pager_parser.add_argument(
        "-l",
        "--links",
        choices=LINK_CHOICES,
        default="auto",
        help="Link scanning and painted keys: auto or never (default: auto)",
    )
    pager_parser.add_argument(
        "-p",
        "--plain",
        action="store_true",
        help="Dump plain text without starting the pager",
    )
    pager_parser.add_argument(
        "-t",
        "--title",
        help="Document title for stdin input",
    )
    pager_parser.add_argument(
        "-w",
        "--wrap",
        type=wrap_width,
        default=markdown_print_width(),
        metavar="WIDTH",
        help=(
            "Wrap prose at WIDTH columns; accepts 'auto', 'none', or 0 "
            f"(default: {markdown_print_width()})"
        ),
    )


__all__ = ["register_pager_parser"]
