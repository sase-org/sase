"""Argument parser definition for the ``sase var`` CLI subcommand."""

from __future__ import annotations

import argparse
from typing import NoReturn


class _VarSetArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        if "the following arguments are required: KEY[=VALUE]" in message:
            message = (
                "at least one KEY=VALUE assignment is required; the value-source "
                "form requires exactly one bare KEY (without '='): "
                "`sase var set KEY --value TEXT` sets exactly one variable"
            )
        super().error(message)


def register_var_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase var`` subcommand parser."""
    var_parser = subparsers.add_parser(
        "var",
        help="Attach output variables to the current SASE agent run",
    )
    var_subparsers = var_parser.add_subparsers(
        dest="var_subcommand",
        help="Variable subcommands",
        parser_class=_VarSetArgumentParser,
    )

    set_parser = var_subparsers.add_parser(
        "set",
        help="Set output variables for the current SASE agent",
        description=(
            "Set one or more output variables with KEY=VALUE assignments, or set "
            "one bare KEY from --value or --value-file."
        ),
        epilog=(
            "examples:\n"
            '  sase var set "summary=tests passed"\n'
            '  sase var set summary --value="tests passed"\n'
            "  sase var set status --value=-ready\n"
            "  sase var set body --value-file - <<'EOF'\n"
            "first line\n"
            "second line\n"
            "EOF\n"
            "  printf 'first line\\nsecond line\\n' | "
            "sase var set body --value-file -"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    set_parser.add_argument(
        "assignments",
        nargs="+",
        metavar="KEY[=VALUE]",
        help=("KEY=VALUE assignment, or one bare KEY with --value or --value-file"),
    )
    value_source = set_parser.add_mutually_exclusive_group()
    value_source.add_argument(
        "-f",
        "--value-file",
        metavar="PATH",
        help="Read the value as UTF-8 text from PATH; use - for stdin",
    )
    value_source.add_argument(
        "-v",
        "--value",
        metavar="TEXT",
        help="Use TEXT as the value verbatim without splitting on whitespace",
    )
