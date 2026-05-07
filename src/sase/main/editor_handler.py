"""Handler for ``sase editor`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_editor_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate editor sub-handler."""
    sub = getattr(args, "editor_subcommand", None)

    if sub == "helper-bridge":
        from sase.integrations.editor_helpers import handle_editor_helper_bridge

        sys.exit(handle_editor_helper_bridge(args))

    print("Usage: sase editor {helper-bridge}", file=sys.stderr)
    sys.exit(1)
