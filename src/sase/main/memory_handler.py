"""Handler for ``sase memory`` subcommands."""

from __future__ import annotations

import argparse
import sys


def _handle_memory_list_command(args: argparse.Namespace) -> None:
    """Handle the ``sase memory list`` dashboard."""
    from sase.memory.cli_list import handle_memory_list_command

    handle_memory_list_command(args)


def _handle_memory_log_command(args: argparse.Namespace) -> None:
    """Handle the ``sase memory log`` summary."""
    from sase.memory.cli_log import handle_memory_log_command

    handle_memory_log_command(args)


def handle_memory_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase memory`` sub-handler."""
    sub = getattr(args, "memory_subcommand", None) or "list"

    if sub == "init":
        from .init_memory_handler import handle_memory_init_command

        handle_memory_init_command(args)
        sys.exit(0)

    if sub == "list":
        _handle_memory_list_command(args)
        sys.exit(0)

    if sub == "read":
        from sase.memory.cli_read import handle_memory_read_command

        handle_memory_read_command(args)
        sys.exit(0)

    if sub == "log":
        _handle_memory_log_command(args)
        sys.exit(0)

    print("Usage: sase memory {init,list,read,log}", file=sys.stderr)
    sys.exit(1)
