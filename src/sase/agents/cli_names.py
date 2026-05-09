"""CLI handlers for permanent agent-name maintenance."""

from __future__ import annotations

import argparse
import json
import sys


def handle_agents_names(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents names`` subcommands."""
    sub = getattr(args, "names_subcommand", None)
    if sub == "migrate-auto":
        from sase.agent.names import run_historical_auto_name_migration

        result = run_historical_auto_name_migration(
            force=bool(getattr(args, "force", False))
        )
        payload = {
            "changed": result.changed,
            "migrated_count": len(result.migrated_names),
            "migrated_names": result.migrated_names,
            "files_changed": list(result.files_changed),
            "skipped_by_marker": result.skipped_by_marker,
        }
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if result.skipped_by_marker:
                print("Historical auto-name migration already completed.")
            else:
                print(
                    "Historical auto-name migration completed: "
                    f"{payload['migrated_count']} name(s), "
                    f"{len(result.files_changed)} file(s) changed."
                )
        return

    print("Usage: sase agents names {migrate-auto}")
    sys.exit(1)
