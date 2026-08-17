"""Handler for ``sase glossary`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_glossary_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase glossary`` sub-handler."""
    sub = getattr(args, "glossary_subcommand", None) or "list"

    if sub == "add":
        from sase.glossary.cli_add import handle_glossary_add_command

        handle_glossary_add_command(args)
        sys.exit(0)

    if sub == "del":
        from sase.glossary.cli_del import handle_glossary_del_command

        handle_glossary_del_command(args)
        sys.exit(0)

    if sub == "list":
        from sase.glossary.cli_list import handle_glossary_list_command

        handle_glossary_list_command(args)
        sys.exit(0)

    if sub == "log":
        from sase.glossary.cli_log import handle_glossary_log_command

        handle_glossary_log_command(args)
        sys.exit(0)

    if sub == "read":
        from sase.glossary.cli_read import handle_glossary_read_command

        handle_glossary_read_command(args)
        sys.exit(0)

    if sub == "show":
        from sase.glossary.cli_show import handle_glossary_show_command

        handle_glossary_show_command(args)
        sys.exit(0)

    print("Usage: sase glossary {add,del,list,log,read,show}", file=sys.stderr)
    sys.exit(1)
