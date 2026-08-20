"""Argument parser definition for the ``sase snippet`` command group."""

from __future__ import annotations

import argparse

_PROJECT_HELP = "Project to query (default: infer from current directory)"


def register_snippet_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``snippet`` command group."""
    snippet_parser = subparsers.add_parser(
        "snippet",
        help="Add, delete, list, and show SASE snippets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect or update the effective snippet catalog for a project. "
            "Xprompt-derived entries are viewable; writable `ace.snippets` "
            "definitions can be added or deleted. Running `sase snippet` "
            "defaults to `sase snippet list`."
        ),
        epilog=(
            "examples:\n"
            "  sase snippet list\n"
            "  sase snippet list todo -f names\n"
            "  sase snippet show greet\n"
            "  sase snippet show greet -f json -p sase\n"
            '  sase snippet add todo "TODO($1)$0"\n'
            '  sase snippet add todo "TODO($1)$0" -t ~/.config/sase/sase.yml\n'
            "  sase snippet delete todo -n\n"
            "  sase snippet delete todo -a -f json"
        ),
    )
    _add_project_option(snippet_parser, default=None)
    snippet_subparsers = snippet_parser.add_subparsers(
        dest="snippet_subcommand",
        help="Snippet subcommands",
    )

    add_parser = snippet_subparsers.add_parser(
        "add",
        help="Add a writable config snippet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Insert TRIGGER with TEMPLATE into the resolved "
            "`ace.snippet_config_path` (or `-t/--target`). Refuses to "
            "overwrite or shadow an existing definition unless `-F/--force` "
            "is given, and names the source that currently wins. `-n/--dry-run` "
            "validates and plans the write without touching the destination."
        ),
        epilog=(
            "examples:\n"
            '  sase snippet add todo "TODO($1)$0"\n'
            '  sase snippet add todo "TODO($1)$0" -F\n'
            '  sase snippet add greet "Hello $1!$0" -t ~/.config/sase/sase.yml\n'
            '  sase snippet add todo "TODO($1)$0" -n -f json -p sase'
        ),
    )
    add_parser.add_argument(
        "trigger",
        metavar="TRIGGER",
        help="Nonblank alphanumeric/underscore trigger to add",
    )
    add_parser.add_argument(
        "template",
        metavar="TEMPLATE",
        help="Nonblank snippet template body",
    )
    add_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the outcome without writing",
    )
    add_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="Overwrite or shadow an existing snippet",
    )
    _add_write_format_option(add_parser)
    _add_project_option(add_parser)
    add_parser.add_argument(
        "-t",
        "--target",
        metavar="PATH",
        default=None,
        help="Writable YAML destination (default: configured path)",
    )

    delete_parser = snippet_subparsers.add_parser(
        "delete",
        help="Delete a writable config snippet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Remove the winning writable `ace.snippets` contribution for "
            "TRIGGER after exact, alias, then unique-prefix lookup. Refuses "
            "to pretend a read-only, plugin, or xprompt-derived entry was "
            "deleted and points at its source instead. Prints the restore "
            "command and any newly revealed definition. `-a/--all` removes "
            "every writable config-layer contribution."
        ),
        epilog=(
            "examples:\n"
            "  sase snippet delete todo\n"
            "  sase snippet delete Todo\n"
            "  sase snippet delete todo -n\n"
            "  sase snippet delete todo -a -p sase -f json"
        ),
    )
    delete_parser.add_argument(
        "trigger",
        metavar="TRIGGER",
        help="Trigger, alias, or unique prefix to delete",
    )
    delete_parser.add_argument(
        "-a",
        "--all",
        dest="all_layers",
        action="store_true",
        help="Remove every writable config-layer contribution",
    )
    delete_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the outcome without writing",
    )
    _add_write_format_option(delete_parser)
    _add_project_option(delete_parser)

    list_parser = snippet_subparsers.add_parser(
        "list",
        help="List effective snippets for a project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List each effective explicit trigger once, optionally filtered "
            "by a case-insensitive substring match against triggers and "
            "generated aliases. `-d/--definitions` extends matching into "
            "raw and composed bodies. Generated aliases are metadata, not "
            "extra rows."
        ),
        epilog=(
            "examples:\n"
            "  sase snippet list\n"
            "  sase snippet list todo\n"
            "  sase snippet list todo --definitions\n"
            "  sase snippet list -f names\n"
            "  sase snippet list -f json -p sase"
        ),
    )
    list_parser.add_argument(
        "pattern",
        metavar="PATTERN",
        nargs="?",
        default=None,
        help="Case-insensitive substring filter over triggers",
    )
    list_parser.add_argument(
        "-d",
        "--definitions",
        action="store_true",
        help="Extend PATTERN matching into snippet bodies",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "names", "table"),
        default="table",
        help="Output format (default: table)",
    )
    _add_project_option(list_parser)

    show_parser = snippet_subparsers.add_parser(
        "show",
        help="Show one snippet's definition and relations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve TRIGGER through exact, alias, then unique-prefix lookup "
            "and print the raw template, composed expansion, source stack, "
            "aliases, calls, backlinks, and diagnostics. Xprompt-derived "
            "entries are viewable and linkable but are source-edited."
        ),
        epilog=(
            "examples:\n"
            "  sase snippet show greet\n"
            "  sase snippet show Greet\n"
            "  sase snippet show greet -f markdown\n"
            "  sase snippet show greet -p sase -f json"
        ),
    )
    show_parser.add_argument(
        "trigger",
        metavar="TRIGGER",
        help="Trigger, alias, or unique prefix to show",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "markdown", "rich"),
        default="rich",
        help="Output format (default: rich)",
    )
    _add_project_option(show_parser)


def _add_write_format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--format",
        choices=("json", "rich"),
        default="rich",
        help="Output format (default: rich)",
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


__all__ = ["register_snippet_parser"]
