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
    )

    sub = getattr(args, "daemon_subcommand", None)
    handlers = {
        "start": handle_daemon_start,
        "stop": handle_daemon_stop,
        "status": handle_daemon_status,
        "doctor": handle_daemon_doctor,
        "rebuild": handle_daemon_rebuild,
    }
    handler = handlers.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase daemon {start,stop,status,doctor,rebuild}",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(handler(args))
