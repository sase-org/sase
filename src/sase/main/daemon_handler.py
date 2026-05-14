"""Handler for ``sase daemon`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_daemon_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate daemon lifecycle handler."""
    from sase.integrations.daemon_lifecycle import (
        handle_daemon_doctor,
        handle_daemon_rebuild,
        handle_daemon_start,
        handle_daemon_status,
        handle_daemon_stop,
        handle_daemon_verify,
        handle_daemon_diff,
    )

    sub = getattr(args, "daemon_subcommand", None)
    handlers = {
        "start": handle_daemon_start,
        "stop": handle_daemon_stop,
        "status": handle_daemon_status,
        "doctor": handle_daemon_doctor,
        "rebuild": handle_daemon_rebuild,
        "verify": handle_daemon_verify,
        "diff": handle_daemon_diff,
    }
    handler = handlers.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase daemon {start,stop,status,doctor,rebuild,verify,diff}",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(handler(args))
