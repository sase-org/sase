"""Handler for ``sase instructions`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_instructions_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase instructions`` sub-handler."""
    sub = getattr(args, "instructions_subcommand", None) or "list"

    if sub == "list":
        from sase.amd.inventory import run_amd_list

        sys.exit(run_amd_list(args))

    print("Usage: sase instructions {list}", file=sys.stderr)
    sys.exit(1)
