"""Hidden supervisor handler for ``sase monitor``."""

from __future__ import annotations

import argparse


def handle_monitor_supervise(args: argparse.Namespace) -> int:
    """Run the detached monitor supervisor for one artifacts dir."""
    from sase.monitor.supervise import run_supervisor

    return run_supervisor(args.artifacts_dir)


__all__ = [
    "handle_monitor_supervise",
]
