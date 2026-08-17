"""Argument parser definition for the ``sase glossary`` command group."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import nonnegative_int

_PROJECT_HELP = "Project to query (default: infer from current directory)"


def register_glossary_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``glossary`` command group."""
    glossary_parser = subparsers.add_parser(
        "glossary",
        help="List and show project glossary terms and their reference closure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the project glossary configured under memory.glossary in "
            "sase/sase.yml. Running `sase glossary` defaults to "
            "`sase glossary list`."
        ),
        epilog=(
            "examples:\n"
            "  sase glossary list\n"
            "  sase glossary list agent -f names\n"
            '  sase glossary show "Agent Hood"\n'
            "  sase glossary show Stitch -d 0 -f markdown\n"
            "  sase glossary -p sase show Stitch"
        ),
    )
    glossary_parser.add_argument(
        "-p",
        "--project",
        metavar="REF",
        default=None,
        help=_PROJECT_HELP,
    )
    glossary_subparsers = glossary_parser.add_subparsers(
        dest="glossary_subcommand",
        help="Glossary subcommands",
    )

    list_parser = glossary_subparsers.add_parser(
        "list",
        help="List glossary terms for a project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List glossary terms, optionally filtered by a case-insensitive "
            "substring match against each term and its display aliases."
        ),
        epilog=(
            "examples:\n"
            "  sase glossary list\n"
            "  sase glossary list hood\n"
            "  sase glossary list agent --definitions\n"
            "  sase glossary list -f names\n"
            "  sase glossary list -f json -p sase"
        ),
    )
    list_parser.add_argument(
        "pattern",
        metavar="PATTERN",
        nargs="?",
        default=None,
        help="Case-insensitive substring filter over terms and aliases",
    )
    list_parser.add_argument(
        "-d",
        "--definitions",
        action="store_true",
        help="Extend PATTERN matching into definition bodies",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "names", "table"),
        default="table",
        help="Output format (default: table)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        metavar="REF",
        default=argparse.SUPPRESS,
        help=_PROJECT_HELP,
    )

    show_parser = glossary_subparsers.add_parser(
        "show",
        help="Print one or more glossary terms and their reference closure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve one or more glossary terms and print each term's "
            "definition plus the recursive closure of terms its definition "
            "depends on, with provenance for every related term."
        ),
        epilog=(
            "examples:\n"
            '  sase glossary show "Agent Hood"\n'
            "  sase glossary show Stitch -d 0\n"
            "  sase glossary show Stitch -f markdown\n"
            "  sase glossary show Stitch -p sase -f json"
        ),
    )
    show_parser.add_argument(
        "term",
        metavar="TERM",
        nargs="+",
        help="One or more term, alias, or slug-form references to resolve",
    )
    show_parser.add_argument(
        "-d",
        "--depth",
        type=nonnegative_int,
        default=None,
        metavar="N",
        help=(
            "Cap recursion depth (default: unlimited); -d 0 prints only the "
            "requested terms"
        ),
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "markdown", "rich"),
        default="rich",
        help="Output format (default: rich)",
    )
    show_parser.add_argument(
        "-p",
        "--project",
        metavar="REF",
        default=argparse.SUPPRESS,
        help=_PROJECT_HELP,
    )


__all__ = ["register_glossary_parser"]
