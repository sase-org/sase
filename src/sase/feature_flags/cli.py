"""Subcommand dispatch for ``sase flag``."""

from __future__ import annotations

import argparse
import sys

from sase.feature_flags.cli_list import handle_flag_list
from sase.feature_flags.cli_new import handle_flag_new
from sase.feature_flags.cli_show import handle_flag_show


def handle_flag_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase flag ...`` command."""
    sub = getattr(args, "flag_subcommand", None) or "list"
    if sub == "list":
        sys.exit(handle_flag_list(args))
    if sub == "new":
        sys.exit(handle_flag_new(args))
    if sub == "show":
        sys.exit(handle_flag_show(args))
    print("Usage: sase flag {list,new,show}", file=sys.stderr)
    sys.exit(2)


__all__ = [
    "handle_flag_command",
]
