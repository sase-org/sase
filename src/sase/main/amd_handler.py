"""Handler for ``sase amd`` subcommands."""

from __future__ import annotations

import argparse
import sys


def _handle_amd_init_command(args: argparse.Namespace) -> int:
    """Handle the ``sase amd init`` command."""
    from sase.amd.cli import run_amd_init

    return run_amd_init(args)


def _handle_amd_list_command(args: argparse.Namespace) -> int:
    """Handle the ``sase amd list`` command."""
    from sase.amd.cli import run_amd_list

    return run_amd_list(args)


def handle_amd_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase amd`` sub-handler."""
    sub = getattr(args, "amd_subcommand", None) or "list"

    if sub == "init":
        sys.exit(_handle_amd_init_command(args))

    if sub == "list":
        sys.exit(_handle_amd_list_command(args))

    print("Usage: sase amd {init,list}", file=sys.stderr)
    sys.exit(1)


def handle_init_amd_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init amd``."""
    sys.exit(_handle_amd_init_command(args))
