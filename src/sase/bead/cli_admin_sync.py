"""Bead sync and conflict-resolution CLI command handlers."""

from __future__ import annotations

import argparse

from sase.bead.cli_common import get_project
from sase.bead.conflict_resolver import handle_resolve_conflicts_command


def handle_bead_sync(args: argparse.Namespace) -> None:
    with get_project() as proj:
        if args.status:
            clean = proj.sync_is_clean()
            if clean:
                print("✓ Bead state is in sync with git")
            else:
                print("○ Bead state has uncommitted changes")
            return
        proj.sync()
        print("✓ Synced bead state to git")


def handle_bead_resolve_conflicts(args: argparse.Namespace) -> None:
    raise SystemExit(handle_resolve_conflicts_command())


__all__ = [
    "handle_bead_resolve_conflicts",
    "handle_bead_sync",
]
