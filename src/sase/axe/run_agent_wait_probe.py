"""One-shot dependency probe the lean waiter runs as a short-lived child.

The lean waiter (``run_agent_lean_wait.py``) stays near 15 MB by never importing
the dependency resolver. When it must resolve a parked runner's dependencies
itself (the ``wait_checks`` heartbeat is stale, or the rare safety probe is
due), it starts this script, which pays the resolver's import cost once and
exits so the memory is returned to the host immediately.

Run it by path with the waiter's interpreter and no extra interpreter flags:

    python run_agent_wait_probe.py --waiting-path W --artifacts-dir D \\
        --project-name P [--bead-sync-hint]

It resolves the dependencies recorded in ``waiting.json`` through
``waiting_marker_dependencies_resolved``, so epic-follow patching stays intact,
and prints exactly one JSON line on stdout:

    {"released": true|false, "satisfied_at": <epoch float or null>}

Everything else (the resolver's own progress lines, tracebacks) goes to stderr.
It exits 0 whenever it produced that line. Any internal error exits nonzero
with no line, which the waiter treats as "not released".
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a parked runner's dependencies once and report."
    )
    parser.add_argument("--waiting-path", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--bead-sync-hint", action="store_true")
    args = parser.parse_args(argv)

    try:
        # The resolver prints progress lines; stdout is reserved for the result.
        with contextlib.redirect_stdout(sys.stderr):
            from sase.axe.run_agent_wait_deps import (
                mark_bead_wait_sync_hint,
                waiting_marker_dependencies_resolved,
            )

            if args.bead_sync_hint:
                mark_bead_wait_sync_hint(args.project_name)
            resolution = waiting_marker_dependencies_resolved(
                Path(args.waiting_path),
                project_name=args.project_name,
                artifacts_dir=args.artifacts_dir,
            )
        released = bool(resolution)
        satisfied_at = getattr(resolution, "satisfied_at", None) if released else None
        payload = {
            "released": released,
            "satisfied_at": (
                float(satisfied_at) if isinstance(satisfied_at, (int, float)) else None
            ),
        }
    except Exception:  # noqa: BLE001 - the waiter reads any failure as "not released".
        traceback.print_exc()
        return 1
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
