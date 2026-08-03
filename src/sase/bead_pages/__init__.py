"""Generated bead pages published into a project's ``--beads`` sidecar.

A bead page is a projection of durable bead state and of associations derived
from the primary repository's history. Nothing in this package persists new
state, so every page is fully re-derivable and every write point can be
best-effort.
"""

from __future__ import annotations

from sase.bead_pages.paths import (
    BEAD_PAGES_DIRNAME,
    bead_lineage_root,
    bead_page_path,
    bead_page_root,
)
from sase.bead_pages.rendering import render_bead_page, render_bead_page_bytes

__all__ = [
    "BEAD_PAGES_DIRNAME",
    "bead_lineage_root",
    "bead_page_path",
    "bead_page_root",
    "render_bead_page",
    "render_bead_page_bytes",
]
