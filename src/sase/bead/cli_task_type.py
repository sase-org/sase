"""``sase bead task-type`` handler."""

from __future__ import annotations

import argparse

from sase.task_types.cli import handle_task_type_command


def handle_bead_task_type(args: argparse.Namespace) -> None:
    """Dispatch one ``sase bead task-type`` action."""

    handle_task_type_command(args)


__all__ = [
    "handle_bead_task_type",
]
