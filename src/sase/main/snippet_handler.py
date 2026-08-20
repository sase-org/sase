"""Handler for ``sase snippet`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_snippet_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase snippet`` sub-handler."""
    sub = getattr(args, "snippet_subcommand", None) or "list"

    if sub == "add":
        from sase.snippet.cli_add import handle_snippet_add_command

        handle_snippet_add_command(args)
        sys.exit(0)

    if sub == "delete":
        from sase.snippet.cli_delete import handle_snippet_delete_command

        handle_snippet_delete_command(args)
        sys.exit(0)

    if sub == "list":
        from sase.snippet.cli_list import handle_snippet_list_command

        handle_snippet_list_command(args)
        sys.exit(0)

    if sub == "show":
        from sase.snippet.cli_show import handle_snippet_show_command

        handle_snippet_show_command(args)
        sys.exit(0)

    print("Usage: sase snippet {add,delete,list,show}", file=sys.stderr)
    sys.exit(1)


__all__ = ["handle_snippet_command"]
