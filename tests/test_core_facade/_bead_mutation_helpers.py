"""Shared helpers for bead-mutation facade tests.

Split from ``tests.test_core_facade.test_bead_mutation``. Public helpers used
by more than one split module live here under public names so no new module
imports a ``_``-prefixed name from another new module.
"""

from __future__ import annotations

from pathlib import Path

from sase.bead.config import save_config
from sase.bead.project import BeadProject

__all__ = ["init_store"]


def init_store(root: Path) -> None:
    """Initialize a golden-prefixed bead store under ``root``."""
    with BeadProject.init(root):
        pass
    save_config(
        root / "sdd/beads",
        {"issue_prefix": "gold", "next_counter": 1, "owner": "owner@example.com"},
    )
