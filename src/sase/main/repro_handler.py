"""Handler for ``sase repro`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_repro_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate reproduction sub-handler."""

    sub = getattr(args, "repro_subcommand", None)
    capture_sub = getattr(args, "repro_capture_subcommand", None)

    if sub == "replay":
        from sase.ace.tui.repro.cli import handle_repro_replay

        sys.exit(handle_repro_replay(args))

    if sub == "capture" and capture_sub == "agents-tab":
        from sase.ace.tui.repro.cli import handle_repro_capture_agents_tab

        sys.exit(handle_repro_capture_agents_tab(args))

    print("Usage: sase repro {capture,replay}", file=sys.stderr)
    sys.exit(1)
