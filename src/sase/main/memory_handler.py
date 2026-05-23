"""Handler for ``sase memory`` subcommands."""

from __future__ import annotations

import argparse
import sys


def _handle_memory_list_command(args: argparse.Namespace) -> None:
    """Placeholder for the Phase 3 ``sase memory list`` dashboard."""
    print(
        "sase memory list: dashboard implementation is not available yet",
        file=sys.stderr,
    )
    sys.exit(1)


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

    print("Usage: sase memory {init,list}", file=sys.stderr)
    sys.exit(1)
