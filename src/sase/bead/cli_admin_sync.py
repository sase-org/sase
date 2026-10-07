"""Bead sync and conflict-resolution CLI command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path

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


def handle_bead_export(args: argparse.Namespace) -> None:
    """Regenerate the ``issues.jsonl`` compatibility projection on demand."""
    import shutil

    from sase.core import bead_mutation_facade as rust_beads

    output = getattr(args, "output", None)
    with get_project() as proj:
        beads_dir = proj.beads_dir
        rust_beads.export_jsonl(beads_dir)
        default_path = beads_dir / "issues.jsonl"
        if output is None:
            print(f"Exported bead state to {default_path}")
            return
        output_path = Path(output).expanduser()
        if output_path != default_path:
            shutil.copy2(default_path, output_path)
        print(f"Exported bead state to {output_path}")


def handle_bead_resolve_conflicts(args: argparse.Namespace) -> None:
    raise SystemExit(handle_resolve_conflicts_command())


__all__ = [
    "handle_bead_export",
    "handle_bead_resolve_conflicts",
    "handle_bead_sync",
]
