"""Handler implementation for the ``sase autonomy`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.autonomy.cli import handle_autonomy_command


def handle_autonomy_group(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase autonomy ...`` command."""
    import sys

    sys.exit(handle_autonomy_command(args))


__all__ = ["handle_autonomy_group"]
