"""Dispatch for the ``sase agent-cli`` command group."""

from __future__ import annotations

import argparse
import sys


def handle_agent_cli_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed agent-CLI command and exit with its handler's code."""
    subcommand = getattr(args, "agent_cli_subcommand", None)
    if subcommand == "install":
        from sase.agent_clis.cli_install import handle_agent_cli_install_command

        sys.exit(handle_agent_cli_install_command(args))
    if subcommand == "list":
        from sase.agent_clis.cli_list import handle_agent_cli_list_command

        sys.exit(handle_agent_cli_list_command(args))
    if subcommand == "update":
        from sase.agent_clis.cli_update import handle_agent_cli_update_command

        sys.exit(handle_agent_cli_update_command(args))

    print("Usage: sase agent-cli {install,list,update}", file=sys.stderr)
    sys.exit(2)


__all__ = ["handle_agent_cli_command"]
