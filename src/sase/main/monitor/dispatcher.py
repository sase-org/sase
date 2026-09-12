"""Subcommand dispatch for ``sase monitor``."""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from .list import handle_monitor_list
from .resume import handle_monitor_resume
from .show import handle_monitor_show
from .start import handle_monitor_start
from .stop import handle_monitor_stop
from .supervise import handle_monitor_supervise


def handle_monitor_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch monitor subcommands."""
    subcommand = getattr(args, "monitor_subcommand", None)
    if subcommand in (None, "list"):
        sys.exit(handle_monitor_list(args))
    if subcommand == "show":
        sys.exit(handle_monitor_show(args))
    if subcommand == "start":
        sys.exit(handle_monitor_start(args))
    if subcommand == "resume":
        sys.exit(handle_monitor_resume(args))
    if subcommand == "stop":
        sys.exit(handle_monitor_stop(args))
    if subcommand == "_supervise":
        sys.exit(handle_monitor_supervise(args))
    print("Usage: sase monitor {list,show,resume,start,stop}", file=sys.stderr)
    sys.exit(1)


__all__ = [
    "handle_monitor_command",
]
