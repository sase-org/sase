"""Generator for the checked-in Footprint feature catalog.

Walks every sase registry into a deterministic ``catalog.jsonl``:

- the full argparse tree (commands and option dests)
- ``build_command_catalog`` over the bundled keymap registry
- every ``KeymapRegistry`` scope field and every built-in mode keymap class
- top-level tabs, artifacts subtabs, config-center tabs, statistics views
- ``ModalScreen`` subclasses under ``src/sase/ace/tui/`` (AST scan)
- bundled macros, generated skill sources, config leaves, AXE jobs
- first-party plugin command words

Hot paths never import this module. The generator uses bundled defaults
only: it never reads the user's config, keymap overrides, saved queries, or
custom modes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sase.footprint._catalog_gen_commands import gen_cli, gen_tui
from sase.footprint._catalog_gen_content import (
    gen_auto,
    gen_config,
    gen_macros,
    gen_modals,
    gen_plugins,
    gen_skills,
    gen_views,
)
from sase.footprint._catalog_gen_shared import ENTRY_KEYS, Entry, load_bundled_config
from sase.footprint.ids import CATALOG_SCHEMA, is_valid_feature_id


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


# symvision: tools/sync_footprint_catalog
def generate_entries() -> list[dict[str, Any]]:
    """Generate the full catalog as sorted entry dicts."""
    cfg = load_bundled_config()
    entries: list[Entry] = []
    entries.extend(gen_cli())
    entries.extend(gen_tui())
    entries.extend(gen_views())
    entries.extend(gen_modals())
    entries.extend(gen_macros())
    entries.extend(gen_skills())
    entries.extend(gen_config(cfg))
    entries.extend(gen_auto(cfg))
    entries.extend(gen_plugins())
    by_id: dict[str, Entry] = {}
    for entry in entries:
        if not is_valid_feature_id(entry.id):
            raise ValueError(f"generated invalid feature ID {entry.id!r}")
        by_id.setdefault(entry.id, entry)
    if len(by_id) != len(entries):
        seen: set[str] = set()
        dupes: set[str] = set()
        for entry in entries:
            if entry.id in seen:
                dupes.add(entry.id)
            seen.add(entry.id)
        raise ValueError(f"duplicate feature IDs: {sorted(dupes)}")
    ordered = [by_id[key] for key in sorted(by_id)]
    return [entry.to_dict() for entry in ordered]


def _compute_rev(entry_lines: list[str]) -> str:
    """Return the 12-hex rev for canonical entry lines."""
    digest = hashlib.sha256(("\n".join(entry_lines) + "\n").encode("utf-8"))
    return digest.hexdigest()[:12]


# symvision: tools/sync_footprint_catalog
def render_catalog(entries: list[dict[str, Any]]) -> str:
    """Render entries to ``catalog.jsonl`` text with a header line."""
    entry_lines = [
        json.dumps(entry, sort_keys=True, ensure_ascii=False) for entry in entries
    ]
    header = {
        "schema": CATALOG_SCHEMA,
        "rev": _compute_rev(entry_lines),
        "count": len(entry_lines),
    }
    return (
        json.dumps(header, sort_keys=True)
        + "\n"
        + "".join(line + "\n" for line in entry_lines)
    )


__all__ = [
    "ENTRY_KEYS",
    "generate_entries",
    "render_catalog",
]
