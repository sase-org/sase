"""Dispatch ``sase artifact link`` subcommands."""

from __future__ import annotations

import argparse
import sys

from sase.artifact_cli.link_migrate import handle_link_migrate_notes
from sase.artifact_cli.link_ops import handle_link_add, handle_link_list, handle_link_rm


def handle_link(args: argparse.Namespace) -> int:
    """Dispatch one parsed ``sase artifact link`` subcommand."""

    handlers = {
        "add": handle_link_add,
        "list": handle_link_list,
        "migrate-notes": handle_link_migrate_notes,
        "rm": handle_link_rm,
    }
    subcommand = getattr(args, "link_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print(
            "Usage: sase artifact link {add,list,migrate-notes,rm}",
            file=sys.stderr,
        )
        return 2
    return handler(args)


__all__ = ["handle_link"]
