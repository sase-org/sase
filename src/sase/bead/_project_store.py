"""Local-store compatibility operations for ``BeadProject``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead.config import load_config, save_config
from sase.bead.ids import IdGenerator, max_top_level_counter
from sase.bead.jsonl import export_to_jsonl
from sase.bead.sync import (
    bead_state_is_clean,
    bead_store_write_lock,
    git_sync,
    rebuild_from_jsonl,
)


class BeadProjectStoreMixin:
    """Sync and SQLite compatibility methods for ``BeadProject``."""

    beads_dir: Path
    _config: dict[str, object]
    _conn_cache: sqlite3.Connection | None
    _id_gen: IdGenerator
    _last_mutation_outcome: dict[str, object]
    _last_prefix_repair: tuple[str, str] | None
    _mutation_changed: bool

    @property
    def _conn(self) -> sqlite3.Connection:
        """Open the compatibility mirror on first legacy use."""
        if self._conn_cache is None:
            rebuild_from_jsonl(self.beads_dir)
            self._conn_cache = db_mod.init_db(self.beads_dir / "beads.db")
        return self._conn_cache

    def _close_connection(self) -> None:
        if self._conn_cache is not None:
            self._conn_cache.close()
            self._conn_cache = None

    def sync(self) -> None:
        """Export compatibility projection and stage bead state in git."""
        with bead_store_write_lock(self.beads_dir) as already_locked:
            self._export()
            git_sync(self.beads_dir, already_locked=already_locked)

    def sync_is_clean(self) -> bool:
        """Check if canonical bead state has uncommitted changes."""
        return bead_state_is_clean(self.beads_dir)

    def _next_child_id(self, parent_id: str) -> str:
        """Generate the next hierarchical child ID ``<parent_id>.<N>``."""
        max_n = self._max_local_child_counter(parent_id)
        return f"{parent_id}.{max_n + 1}"

    def _max_local_child_counter(self, parent_id: str) -> int:
        """Return the highest direct child counter currently in the local DB."""
        prefix = f"{parent_id}."
        rows = self._conn.execute(
            "SELECT id FROM issues WHERE id LIKE ?", (f"{prefix}%",)
        ).fetchall()
        max_n = 0
        for row in rows:
            suffix = row["id"][len(prefix) :]
            # Only consider direct children (no dots in suffix)
            if "." not in suffix:
                try:
                    n = int(suffix)
                    max_n = max(max_n, n)
                except ValueError:
                    pass
        return max_n

    def _next_top_level_counter(self) -> int:
        """Return the next safe top-level counter for this bead store."""
        prefix = str(self._config.get("issue_prefix", "beads"))
        return max(
            self._id_gen.counter,
            max_top_level_counter(prefix, self.beads_dir) + 1,
        )

    def _export(self) -> None:
        """Export current state to JSONL."""
        from sase.core import bead_mutation_facade as rust_beads

        try:
            rust_beads.export_jsonl(self.beads_dir)
        except (AttributeError, ImportError, ValueError):
            export_to_jsonl(self._conn, self.beads_dir / "issues.jsonl")
        self._refresh_db_from_jsonl()

    def _save_counter(self) -> None:
        """Persist the ID counter to config."""
        self._config["next_counter"] = self._id_gen.counter
        save_config(self.beads_dir, self._config)

    def _repair_stale_key_prefix(self) -> None:
        """Forward-repair a leaked ProjectSpec-key issue prefix before minting."""
        self._last_prefix_repair = None
        from sase.bead.prefix_policy import repair_stale_key_prefix

        report = repair_stale_key_prefix(self.beads_dir)
        if report is None:
            return
        self._refresh_db_from_jsonl()
        self._last_prefix_repair = report

    def _record_mutation_outcome(self, outcome: dict[str, object]) -> None:
        """Accumulate honest core mutation results for commit gating."""
        self._last_mutation_outcome = outcome.copy()
        self._mutation_changed |= bool(outcome.get("changed", True))

    def _refresh_db_from_jsonl(self) -> None:
        """Refresh lightweight config state after a Rust-owned mutation.

        The SQLite compatibility mirror is rebuilt lazily on its next use,
        using ``issues.jsonl`` mtimes.
        """
        self._close_connection()
        self._config = load_config(self.beads_dir)
        raw_counter = self._config.get("next_counter", 1)
        counter = raw_counter if isinstance(raw_counter, int) else int(str(raw_counter))
        self._id_gen = IdGenerator(
            str(self._config.get("issue_prefix", "beads")), counter
        )
