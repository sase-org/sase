"""``sase artifact link migrate-notes`` dry-run and apply gate."""

from __future__ import annotations

import argparse
import json
import sys

from sase.sdd.artifact_link_store import (
    artifact_links_disabled_message,
    artifact_links_enabled,
)

_MIGRATE_NOTES_SCHEMA_VERSION = 1
_APPLY_UNAVAILABLE = (
    "migrate-notes --apply writes bead link events; that mutation path "
    "lands with the beads phase"
)


def handle_link_migrate_notes(args: argparse.Namespace) -> int:
    """Dry-run RELATED: migration, or refuse apply until beads mutation lands."""

    apply = bool(getattr(args, "apply", False))
    if apply and not artifact_links_enabled():
        print(f"Error: {artifact_links_disabled_message()}", file=sys.stderr)
        return 1
    if apply:
        print(f"Error: {_APPLY_UNAVAILABLE}", file=sys.stderr)
        return 1

    payload = {
        "schema_version": _MIGRATE_NOTES_SCHEMA_VERSION,
        "mode": "dry_run",
        "converted": [],
        "worklist": [],
        "note": (
            "RELATED: note conversion is owned by the beads phase; this "
            "dry-run does not guess. Re-run with --apply after that path lands."
        ),
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print("Dry run: RELATED: note migration.")
    print(payload["note"])
    print("converted: 0")
    print("worklist: 0")
    return 0


__all__ = ["handle_link_migrate_notes"]
