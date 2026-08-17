"""Handler for ``sase bead epic-symbols``."""

from __future__ import annotations

import argparse
import json
import sys

from sase.bead.cli_common import get_read_view
from sase.bead.cli_dep_render import ANSI_BOLD_BLUE, resolve_color, styled
from sase.bead.epic_symbols import (
    discover_justfile,
    entries_for_beads,
    load_epic_symbol_entries,
)


def handle_bead_epic_symbols(args: argparse.Namespace) -> None:
    """List Justfile ``--epic-symbol`` entries, optionally scoped to one bead."""
    start = None
    justfile = discover_justfile(start)
    entries = load_epic_symbol_entries(start)
    target_id = getattr(args, "id", None)
    if target_id:
        with get_read_view() as view:
            try:
                target_id = view.resolve_id(target_id)
            except KeyError:
                print(f"Error: issue not found: {target_id}", file=sys.stderr)
                sys.exit(1)
        entries = entries_for_beads(entries, [target_id])

    fmt = getattr(args, "format", "compact")
    if fmt == "json":
        payload = {
            "justfile": str(justfile) if justfile is not None else None,
            "bead_id": target_id,
            "entries": [
                {
                    "bead_id": entry.bead_id,
                    "symbol": entry.symbol,
                    "raw": entry.raw,
                    "flag": entry.flag,
                }
                for entry in entries
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    if not entries:
        if target_id:
            print(f"No --epic-symbol entries for {target_id}.")
        else:
            print("No --epic-symbol entries in this working tree.")
        return

    use_color = resolve_color(getattr(args, "color", "auto"))
    if justfile is not None:
        print(f"Justfile: {justfile}")
    for entry in entries:
        bead = styled(entry.bead_id, ANSI_BOLD_BLUE, use_color)
        print(f'--epic-symbol "{bead}({entry.symbol})"')
