"""Handler implementation for the ``sase plugin`` CLI subcommand."""

from __future__ import annotations

import argparse
import sys


def handle_plugin_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase plugin ...`` command to its handler."""
    sub = getattr(args, "plugin_subcommand", None)
    if sub == "install":
        from sase.plugins.cli_install import handle_plugin_install_command

        sys.exit(handle_plugin_install_command(args))
    if sub == "list":
        from sase.plugins.cli_list import handle_plugin_list_command

        sys.exit(handle_plugin_list_command(args))
    if sub == "show":
        from sase.plugins.cli_show import handle_plugin_show_command

        sys.exit(handle_plugin_show_command(args))
    if sub == "uninstall":
        from sase.plugins.cli_uninstall import handle_plugin_uninstall_command

        sys.exit(handle_plugin_uninstall_command(args))
    if sub == "update":
        from sase.plugins.cli_update import handle_plugin_update_command

        sys.exit(handle_plugin_update_command(args))

    print("Usage: sase plugin {install,list,show,uninstall,update}", file=sys.stderr)
    sys.exit(2)
