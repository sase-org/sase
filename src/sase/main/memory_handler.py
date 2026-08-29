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


def _handle_memory_agent_docs_command(args: argparse.Namespace) -> None:
    """Dispatch the ``sase memory agent-docs`` group."""
    sub = getattr(args, "agent_docs_subcommand", None) or "list"

    if sub == "list":
        from sase.amd.inventory import run_amd_list

        sys.exit(run_amd_list(args))

    print("Usage: sase memory agent-docs {list}", file=sys.stderr)
    sys.exit(1)


def _handle_memory_web_command(args: argparse.Namespace) -> None:
    """Dispatch the ``sase memory web`` group."""
    sub = getattr(args, "memory_web_subcommand", None) or "list"

    if sub == "list":
        from sase.memory.web import handle_memory_web_list_command

        handle_memory_web_list_command(args)
        return

    if sub == "show":
        from sase.memory.web import handle_memory_web_show_command

        handle_memory_web_show_command(args)
        return

    print("Usage: sase memory web {list,show}", file=sys.stderr)
    sys.exit(1)


def handle_memory_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase memory`` sub-handler."""
    sub = getattr(args, "memory_subcommand", None) or "list"

    if sub == "agent-docs":
        _handle_memory_agent_docs_command(args)
        sys.exit(0)

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

    if sub == "show":
        from sase.memory.cli_show import handle_memory_show_command

        handle_memory_show_command(args)
        sys.exit(0)

    if sub == "log":
        _handle_memory_log_command(args)
        sys.exit(0)

    if sub == "web":
        _handle_memory_web_command(args)
        sys.exit(0)

    print(
        "Usage: sase memory {agent-docs,init,list,log,read,show,web}",
        file=sys.stderr,
    )
    sys.exit(1)
