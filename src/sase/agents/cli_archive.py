"""Archive maintenance commands for dismissed agent bundles."""

from __future__ import annotations

import argparse
import json
import sys


def handle_agents_archive(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents archive`` subcommands."""

    sub = getattr(args, "archive_subcommand", None)
    if sub == "rebuild-index":
        from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index

        indexed, skipped = rebuild_dismissed_bundle_index()
        print(f"Indexed {indexed} dismissed bundles; skipped {skipped} corrupt files.")
        sys.exit(0)

    if sub == "verify":
        from sase.ace.dismissed_agents import verify_dismissed_bundle_index

        result = verify_dismissed_bundle_index()
        print(json.dumps(result, indent=2, sort_keys=True))
        sys.exit(0 if result["ok"] else 1)

    print("Usage: sase agents archive {rebuild-index,verify}")
    sys.exit(1)
