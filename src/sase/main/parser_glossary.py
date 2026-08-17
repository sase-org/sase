"""Argument parser definition for the ``sase glossary`` command group."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import nonnegative_int

_PROJECT_HELP = "Project to query (default: infer from current directory)"


def register_glossary_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``glossary`` command group."""
    glossary_parser = subparsers.add_parser(
        "glossary",
        help="List, show, and audit project glossary terms and their closure",
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
            "  sase glossary -p sase show Stitch\n"
            '  sase glossary read "Agent Hood" -r "Need the hood/agent distinction"\n'
            "  sase glossary log\n"
            "  sase glossary log -t Stitch -a agent-a"
        ),
    )
    _add_project_option(glossary_parser, default=None)
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
    _add_project_option(list_parser)

    log_parser = glossary_subparsers.add_parser(
        "log",
        help="Summarize or inspect audited glossary reads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Summarize audited glossary reads recorded by `sase glossary read`. "
            "The default view is a dashboard grouped by term, by agent, and by "
            "event. Filters are reflected in the header so a filtered view "
            "cannot be mistaken for the whole log."
        ),
        epilog=(
            "examples:\n"
            "  sase glossary log\n"
            "  sase glossary log -t Stitch\n"
            "  sase glossary log -a agent-a -f json\n"
            "  sase glossary log -i <read-id>"
        ),
    )
    log_parser.add_argument(
        "-a",
        "--agent",
        metavar="NAME",
        default=None,
        help="Only include reads by the given agent",
    )
    log_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format (default: table)",
    )
    log_parser.add_argument(
        "-i",
        "--id",
        metavar="READ_ID",
        default=None,
        help="Show one event by id or unambiguous id prefix",
    )
    _add_project_option(log_parser)
    log_parser.add_argument(
        "-t",
        "--term",
        metavar="TERM",
        default=None,
        help="Only include reads that requested or expanded this term",
    )

    read_parser = glossary_subparsers.add_parser(
        "read",
        help="Print glossary terms and record an audited read",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve one or more glossary terms exactly like "
            "`sase glossary show`, then append one attributable audit event "
            "before printing. A non-empty -r/--reason is required; a "
            "definition is never printed unless the read was recorded."
        ),
        epilog=(
            "examples:\n"
            '  sase glossary read "Agent Hood" -r "Need the hood/agent distinction"\n'
            '  sase glossary read Stitch -d 0 -r "Confirm stitch vs commit"\n'
            '  sase glossary read Stitch -p sase -f markdown -r "Prompt context"'
        ),
    )
    _add_closure_arguments(read_parser, require_reason=True)

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
    _add_closure_arguments(show_parser)


def _add_project_option(
    parser: argparse.ArgumentParser, *, default: object = argparse.SUPPRESS
) -> None:
    parser.add_argument(
        "-p",
        "--project",
        metavar="REF",
        default=default,
        help=_PROJECT_HELP,
    )


def _add_closure_arguments(
    parser: argparse.ArgumentParser, *, require_reason: bool = False
) -> None:
    parser.add_argument(
        "term",
        metavar="TERM",
        nargs="+",
        help="One or more term, alias, or slug-form references to resolve",
    )
    parser.add_argument(
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
    parser.add_argument(
        "-f",
        "--format",
        choices=("json", "markdown", "rich"),
        default="rich",
        help="Output format (default: rich)",
    )
    _add_project_option(parser)
    if require_reason:
        parser.add_argument(
            "-r",
            "--reason",
            required=True,
            help="Non-empty reason for the audited glossary read",
        )


__all__ = ["register_glossary_parser"]
