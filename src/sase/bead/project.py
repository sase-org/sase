"""BeadProject: public API for beads issue tracking."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sase.bead._project_mutations import BeadProjectMutationMixin
from sase.bead._project_queries import BeadProjectQueryMixin
from sase.bead._project_store import BeadProjectStoreMixin
from sase.bead._project_types import (
    AlreadyReadyError,
    EpicPreclaimRollback,
    NotAPlanError,
)
from sase.bead.config import get_default_config, load_config
from sase.bead.ids import IdGenerator

BEADS_DIRNAME = "sdd/beads"
"""Default beads subdirectory name (used in in-tree mode)."""

BEADS_DIRNAME_NON_VC = "beads"
"""Beads subdirectory name inside .sase/sdd/ (local/separate-repo modes)."""

BEADS_DIRNAME_ROOT = "."
"""Beads dirname that makes the dedicated sidecar root the bead directory."""


class BeadProject(
    BeadProjectMutationMixin,
    BeadProjectQueryMixin,
    BeadProjectStoreMixin,
):
    """Main API for beads issue tracking.

    Preserves the historical Python API while delegating storage, reads, and
    mutations to Rust-backed facades. The local SQLite connection is kept as a
    compatibility mirror for legacy helpers/tests that still need one.
    """

    def __init__(
        self, root_dir: str | Path, beads_dirname: str = BEADS_DIRNAME
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.beads_dir = self.root_dir / beads_dirname
        if not self.beads_dir.exists():
            raise FileNotFoundError(
                f"No {beads_dirname}/ directory found at {self.root_dir}. "
                "Run 'sase bead init' first."
            )
        self._config: dict[str, object] = load_config(self.beads_dir)
        self._conn_cache: sqlite3.Connection | None = None
        self._mutation_changed = False
        self._last_mutation_outcome: dict[str, object] = {}
        self._last_prefix_repair: tuple[str, str] | None = None
        prefix = str(self._config.get("issue_prefix", "beads"))
        raw_counter = self._config.get("next_counter", 1)
        counter = raw_counter if isinstance(raw_counter, int) else int(str(raw_counter))
        self._id_gen = IdGenerator(prefix, counter)

    def __enter__(self) -> BeadProject:
        return self

    def __exit__(self, *_: object) -> None:
        self._close_connection()

    @property
    def owner(self) -> str:
        """Return the configured bead-store owner."""
        owner = self._config.get("owner", "")
        return owner if isinstance(owner, str) else str(owner)

    @property
    def mutation_changed(self) -> bool:
        """Whether any Rust-backed mutation changed this project instance."""
        return self._mutation_changed

    @property
    def last_mutation_outcome(self) -> dict[str, object]:
        """Return the most recent Rust mutation outcome."""
        return self._last_mutation_outcome.copy()

    @property
    def last_prefix_repair(self) -> tuple[str, str] | None:
        """Return the most recent automatic issue-prefix repair."""
        return self._last_prefix_repair

    @staticmethod
    def init(root_dir: str | Path, beads_dirname: str = BEADS_DIRNAME) -> BeadProject:
        """Create a new beads directory and return a BeadProject."""
        root = Path(root_dir).resolve()
        config = get_default_config(root)
        from sase.bead import db as db_mod
        from sase.core import bead_mutation_facade as rust_beads

        rust_beads.init_store(
            root,
            beads_dirname,
            issue_prefix=str(config.get("issue_prefix", "beads")),
            owner=str(config.get("owner", "")),
        )
        conn = db_mod.init_db(root / beads_dirname / "beads.db")
        conn.close()
        return BeadProject(root, beads_dirname=beads_dirname)

    def _current_time(self) -> str:
        """Resolve the clock through this public module for test compatibility."""
        return _now()


def _now() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "AlreadyReadyError",
    "BEADS_DIRNAME",
    "BEADS_DIRNAME_NON_VC",
    "BEADS_DIRNAME_ROOT",
    "BeadProject",
    "EpicPreclaimRollback",
    "NotAPlanError",
]
