"""Handler for ``sase telemetry`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_telemetry_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate telemetry sub-handler."""
    sub = getattr(args, "telemetry_subcommand", None)

    if sub == "cleanup-test-data":
        from sase.telemetry.cli_cleanup_test_data import (
            handle_telemetry_cleanup_test_data,
        )

        handle_telemetry_cleanup_test_data(args)
        sys.exit(0)

    if sub == "health":
        from sase.telemetry.cli_health import handle_telemetry_health

        handle_telemetry_health(args)
        # handle_telemetry_health calls sys.exit() itself with the appropriate code

    if sub == "list":
        from sase.telemetry.cli_list import handle_telemetry_list

        handle_telemetry_list(args)
        sys.exit(0)

    if sub == "snapshot":
        from sase.telemetry.cli_snapshot import handle_telemetry_snapshot

        handle_telemetry_snapshot(args)
        sys.exit(0)

    if sub == "status":
        from sase.telemetry.cli_status import handle_telemetry_status

        handle_telemetry_status()
        sys.exit(0)

    print("Usage: sase telemetry {cleanup-test-data,health,list,snapshot,status}")
    sys.exit(1)
