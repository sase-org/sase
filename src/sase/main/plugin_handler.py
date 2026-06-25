"""Handler implementation for the ``sase plugin`` CLI subcommand."""

from __future__ import annotations

import argparse
import sys


def handle_plugin_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase plugin ...`` command to its handler."""
    sub = getattr(args, "plugin_subcommand", None)
    if sub == "list":
        from sase.plugins.cli_list import handle_plugin_list_command

        sys.exit(handle_plugin_list_command(args))
    if sub == "show":
        from sase.plugins.cli_show import handle_plugin_show_command

        sys.exit(handle_plugin_show_command(args))

    print("Usage: sase plugin {list,show}", file=sys.stderr)
    sys.exit(2)
