"""Thin dispatcher for the ``sase artifact`` command group."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import NoReturn


def handle_artifact_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch one parsed artifact subcommand and exit with its result."""

    from sase.artifact_cli import (
        handle_create,
        handle_doctor,
        handle_link,
        handle_list,
        handle_open,
        handle_pane,
        handle_path,
        handle_prune,
        handle_read,
        handle_reclaim,
        handle_show,
        handle_stats,
        handle_trash,
    )

    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "create": handle_create,
        "doctor": handle_doctor,
        "link": handle_link,
        "list": handle_list,
        "open": handle_open,
        "pane": handle_pane,
        "path": handle_path,
        "prune": handle_prune,
        "read": handle_read,
        "reclaim": handle_reclaim,
        "show": handle_show,
        "stats": handle_stats,
        "trash": handle_trash,
    }
    subcommand = getattr(args, "artifact_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print(
            "Usage: sase artifact "
            "{create,doctor,link,list,open,pane,path,prune,read,reclaim,show,stats,trash}",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        exit_code = handler(args)
    except Exception as exc:
        print(f"Error: sase artifact {subcommand} failed: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(exit_code)


__all__ = ["handle_artifact_command"]
