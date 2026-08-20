"""Handler implementation for the ``sase final`` command group."""

from __future__ import annotations

import argparse
import sys

from sase.finalizers.cli import (
    handle_final_doctor,
    handle_final_list,
    handle_final_show,
)


def handle_final_command(args: argparse.Namespace) -> None:
    """Dispatch a ``sase final`` subcommand."""

    subcommand = getattr(args, "final_subcommand", None)
    format_name = getattr(args, "format", "pretty")
    if subcommand == "list":
        sys.exit(handle_final_list(format_name=format_name))
    if subcommand == "show":
        sys.exit(handle_final_show(args.instance, format_name=format_name))
    if subcommand == "doctor":
        sys.exit(handle_final_doctor(format_name=format_name))

    print("Usage: sase final {list,show,doctor}")
    sys.exit(1)


__all__ = ["handle_final_command"]
