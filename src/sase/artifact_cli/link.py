"""Dispatch ``sase artifact link`` subcommands."""

from __future__ import annotations

import argparse
import sys

from sase.artifact_cli.link_migrate import handle_link_migrate_notes
from sase.artifact_cli.link_ops import handle_link_add, handle_link_list, handle_link_rm
from sase.artifact_cli.link_relations import handle_link_relation
from sase.artifact_cli.link_suggest import handle_link_suggest


def handle_link(args: argparse.Namespace) -> int:
    """Dispatch one parsed ``sase artifact link`` subcommand."""

    handlers = {
        "add": handle_link_add,
        "list": handle_link_list,
        "migrate-notes": handle_link_migrate_notes,
        "relation": handle_link_relation,
        "rm": handle_link_rm,
        "suggest": handle_link_suggest,
    }
    subcommand = getattr(args, "link_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print(
            "Usage: sase artifact link {add,list,migrate-notes,relation,rm,suggest}",
            file=sys.stderr,
        )
        return 2
    return handler(args)


__all__ = ["handle_link"]
