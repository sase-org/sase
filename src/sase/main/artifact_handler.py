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
        handle_list,
        handle_open,
        handle_path,
        handle_show,
    )

    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "create": handle_create,
        "doctor": handle_doctor,
        "list": handle_list,
        "open": handle_open,
        "path": handle_path,
        "show": handle_show,
    }
    subcommand = getattr(args, "artifact_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print(
            "Usage: sase artifact {create,doctor,list,open,path,show}",
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
