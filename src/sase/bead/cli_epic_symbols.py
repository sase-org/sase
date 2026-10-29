"""Handler for ``sase bead epic-symbols``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sase.bead.cli_dep_render import ANSI_BOLD_BLUE, resolve_color, styled
from sase.bead.epic_symbols import (
    entries_for_beads,
    load_epic_symbol_scan,
)


def _entry_sources_suffix(entry: Any) -> str:
    if not entry.origins:
        return ""
    return f" [{', '.join(entry.origins)}]"


def handle_bead_epic_symbols(args: argparse.Namespace) -> None:
    """List Justfile ``--epic-symbol`` entries, optionally scoped to one bead.

    Reads the working tree's Justfile and the default branch's Justfile; a
    fetch or read failure warns loudly and falls back to the local rows.
    """
    start = None
    target_id = getattr(args, "id", None)
    if target_id:
        requested_id = str(target_id)
        context = _resolve_symbol_bead_context(requested_id)
        target_id = (
            str(context.resolved_ids[0]) if context.resolved_ids else requested_id
        )
        start = _symbol_scan_start(context)
        from sase.bead.assigned_near_miss import warn_if_assigned_near_miss

        warn_if_assigned_near_miss([requested_id, target_id])
    scan = load_epic_symbol_scan(start)
    if scan.upstream_warning is not None:
        print(scan.upstream_warning, file=sys.stderr)
    entries = list(scan.entries)
    if target_id:
        entries = entries_for_beads(entries, [target_id])

    fmt = getattr(args, "format", "compact")
    if fmt == "json":
        payload = {
            "justfile": str(scan.local_justfile)
            if scan.local_justfile is not None
            else None,
            "upstream_justfile": scan.upstream_justfile,
            "upstream_stale": scan.upstream_stale,
            "upstream_warning": scan.upstream_warning,
            "bead_id": target_id,
            "entries": [
                {
                    "bead_id": entry.bead_id,
                    "symbol": entry.symbol,
                    "raw": entry.raw,
                    "flag": entry.flag,
                    "sources": list(entry.origins),
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
    if scan.local_justfile is not None:
        print(f"Justfile: {scan.local_justfile}")
    if scan.upstream_justfile is not None:
        stale = " (stale: fetch failed)" if scan.upstream_stale else ""
        print(f"Upstream Justfile: {scan.upstream_justfile}{stale}")
    for entry in entries:
        bead = styled(entry.bead_id, ANSI_BOLD_BLUE, use_color)
        print(f'--epic-symbol "{bead}({entry.symbol})"{_entry_sources_suffix(entry)}')


def _resolve_symbol_bead_context(target_id: str) -> Any:
    from sase.bead.operation_context import (
        BeadOperationRoutingError,
        resolve_operation_context_for_targets,
    )

    try:
        return resolve_operation_context_for_targets([target_id])
    except BeadOperationRoutingError as exc:
        from sase.bead.assigned_near_miss import annotate_not_found_message

        print(
            f"Error: {annotate_not_found_message(str(exc), requested=target_id)}",
            file=sys.stderr,
        )
        sys.exit(1)


def _symbol_scan_start(context: Any) -> Path | None:
    from sase.bead.operation_context import symbol_scan_start_for_operation_context

    return symbol_scan_start_for_operation_context(context)
