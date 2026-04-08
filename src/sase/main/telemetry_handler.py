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
        from sase.telemetry.cli_snapshot import handle_telemetry_snapshot

        handle_telemetry_snapshot(args)
        sys.exit(0)

    if sub == "dashboard":
        from sase.telemetry.cli_dashboard import handle_telemetry_dashboard

        handle_telemetry_dashboard(args)
        sys.exit(0)

    if sub == "health":
        from sase.telemetry.cli_health import handle_telemetry_health

        handle_telemetry_health(args)
        # handle_telemetry_health calls sys.exit() itself with the appropriate code

    if sub == "export-config":
        from sase.telemetry.cli_export_config import handle_telemetry_export_config

        handle_telemetry_export_config(args)
        sys.exit(0)

    print("Usage: sase telemetry {status,list,snapshot,dashboard,health,export-config}")
    sys.exit(1)
