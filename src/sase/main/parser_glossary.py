"""Argument parser definition for the ``sase glossary`` command group."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import nonnegative_int

_PROJECT_HELP = "Project to query (default: infer from current directory)"


def register_glossary_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``glossary`` command group."""
    glossary_parser = subparsers.add_parser(
        "glossary",
        help="Add, delete, list, show, and audit project glossary terms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect or update the project glossary, which lives in the "
            "`glossary` memory web once a project migrates "
            "(`sase memory web migrate glossary`); `memory.glossary` in "
            "sase/sase.yml is accepted until the next release. Running "
            "`sase glossary` defaults to `sase glossary list`."
        ),
        epilog=(
            "examples:\n"
            "  sase glossary list\n"
            "  sase glossary list agent -f names\n"
            "  sase glossary all\n"
            '  sase glossary show Stitch Patch "Agent Hood"\n'
            '  sase glossary show "Agent Hood"\n'
            "  sase glossary show Stitch -d 0 -f markdown\n"
            "  sase glossary -p sase show Stitch\n"
            '  sase glossary read Stitch Patch "Agent Hood" '
            '-r "Need the patch/stitch vocabulary"\n'
            '  sase glossary read "Agent Hood" -r "Need the hood/agent distinction"\n'
            "  sase glossary log\n"
            "  sase glossary log -t Stitch -a agent-a\n"
            '  sase glossary add "Test Term" "A test term." -a tt\n'
            '  sase glossary del "Test Term"\n'
            "  sase glossary del tt -n"
        ),
    )
    _add_project_option(glossary_parser, default=None)
    glossary_subparsers = glossary_parser.add_subparsers(
        dest="glossary_subcommand",
        help="Glossary subcommands",
    )

    add_parser = glossary_subparsers.add_parser(
        "add",
        help="Add a glossary term to a project's config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Insert a glossary term into the target project's sase/sase.yml "
            "after Rust validation. New terms land in sorted order. Agent "
            "instruction files are regenerated afterward unless -I/--no-init "
            "is passed."
        ),
        epilog=(
            "examples:\n"
            '  sase glossary add "Test Term" '
            '"A test term that references Agent Hood."\n'
            '  sase glossary add "Test Term" "A test term." -a tt -a test\n'
            '  sase glossary add "Test Term" "A test term." -p sase -f json\n'
            '  sase glossary add "Test Term" "A test term." -I'
        ),
    )
    add_parser.add_argument(
        "term",
        metavar="TERM",
        help="Canonical term to add",
    )
    add_parser.add_argument(
        "definition",
        metavar="DEFINITION",
        help="Definition body for the new term",
    )
    add_parser.add_argument(
        "-a",
        "--alias",
        action="append",
        default=None,
        metavar="ALIAS",
        help="Display alias to attach (repeatable)",
    )
    _add_write_format_option(add_parser)
    _add_no_init_option(add_parser)
    _add_project_option(add_parser)

    all_parser = glossary_subparsers.add_parser(
        "all",
        help="Print every glossary term in full",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print every glossary term configured for a project, "
            "alphabetically, with aliases, the full definition, "
            "underlined cross-references, and inbound backlinks. "
            "`sase glossary list` is a table of truncated summaries; "
            "`sase glossary show` prints named terms plus their "
            "reference closure. This command is not an audited read; "
            'agents must use `sase glossary read TERM -r "<why>"`.'
        ),
        epilog=(
            "examples:\n"
            "  sase glossary all\n"
            "  sase glossary all -f markdown\n"
            "  sase glossary all -f json\n"
            "  sase glossary all -p sase"
        ),
    )
    _add_closure_format_option(all_parser)
    _add_project_option(all_parser)

    del_parser = glossary_subparsers.add_parser(
        "del",
        help="Delete a glossary term and print its restore command",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Remove a glossary term after resolving TERM through the same "
            "alias, slug, and unique-prefix lookup as `sase glossary show`. "
            "Prints the exact `sase glossary add` command that restores the "
            "entry. -n/--dry-run prints that outcome without writing."
        ),
        epilog=(
            "examples:\n"
            '  sase glossary del "Test Term"\n'
            "  sase glossary del tt\n"
            "  sase glossary del tt -n\n"
            '  sase glossary del "Test Term" -p sase -f json\n'
            '  sase glossary del "Test Term" -I'
        ),
    )
    del_parser.add_argument(
        "term",
        metavar="TERM",
        help="Term, alias, or unique prefix to delete",
    )
    _add_write_format_option(del_parser)
    _add_no_init_option(del_parser)
    del_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the outcome without writing",
    )
    _add_project_option(del_parser)

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
            "before printing. Pass every term you need in one command so "
            "shared related terms are printed once. A non-empty -r/--reason "
            "is required; a definition is never printed unless the read was "
            "recorded."
        ),
        epilog=(
            "examples:\n"
            '  sase glossary read Stitch Patch "Agent Hood" '
            '-r "Need the patch/stitch vocabulary"\n'
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
            "definition plus the recursive closure of terms those "
            "definitions depend on, with provenance for every related term. "
            "Pass every term you need in one command so shared related terms "
            "are printed once."
        ),
        epilog=(
            "examples:\n"
            '  sase glossary show Stitch Patch "Agent Hood"\n'
            '  sase glossary show "Agent Hood"\n'
            "  sase glossary show Stitch -d 0\n"
            "  sase glossary show Stitch -f markdown\n"
            "  sase glossary show Stitch -p sase -f json"
        ),
    )
    _add_closure_arguments(show_parser)


def _add_closure_format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--format",
        choices=("json", "markdown", "rich"),
        default="rich",
        help="Output format (default: rich)",
    )


def _add_write_format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--format",
        choices=("json", "rich"),
        default="rich",
        help="Output format (default: rich)",
    )


def _add_no_init_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-I",
        "--no-init",
        action="store_true",
        help="Skip regenerating agent instruction files",
    )


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
    _add_closure_format_option(parser)
    _add_project_option(parser)
    if require_reason:
        parser.add_argument(
            "-r",
            "--reason",
            required=True,
            help="Non-empty reason for the audited glossary read",
        )


__all__ = ["register_glossary_parser"]
