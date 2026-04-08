"""Handler for ``sase telemetry`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_telemetry_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate telemetry sub-handler."""
    sub = getattr(args, "telemetry_subcommand", None)

    if sub == "status":
        from sase.telemetry.cli_status import handle_telemetry_status

        handle_telemetry_status()
        sys.exit(0)

    if sub == "list":
        from sase.telemetry.cli_list import handle_telemetry_list

        handle_telemetry_list(args)
        sys.exit(0)

    if sub == "snapshot":
        print("sase telemetry snapshot: not yet implemented (Phase 2)")
        sys.exit(1)

    if sub == "dashboard":
        print("sase telemetry dashboard: not yet implemented (Phase 3)")
        sys.exit(1)

    if sub == "health":
        print("sase telemetry health: not yet implemented (Phase 3)")
        sys.exit(1)

    print("Usage: sase telemetry {status,list,snapshot,dashboard,health}")
    sys.exit(1)
