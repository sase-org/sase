"""Handler implementation for the ``sase flag`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.feature_flags.cli import handle_flag_command


def handle_flag_group(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase flag ...`` command."""
    handle_flag_command(args)


__all__ = ["handle_flag_group"]
