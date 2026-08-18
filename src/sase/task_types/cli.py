"""Dispatch for ``sase bead task-type``."""

from __future__ import annotations

import argparse
import sys

from .cli_list import handle_task_type_list
from .cli_show import handle_task_type_show


def handle_task_type_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase bead task-type ...`` command."""

    sub = getattr(args, "task_type_subcommand", None) or "list"
    if sub == "list":
        sys.exit(handle_task_type_list(args))
    if sub == "show":
        sys.exit(handle_task_type_show(args))
    print("Usage: sase bead task-type {list,show}", file=sys.stderr)
    sys.exit(2)


__all__ = [
    "handle_task_type_command",
]
