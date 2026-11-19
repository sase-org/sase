"""Local-store operations for ``BeadProject``."""

from __future__ import annotations

from pathlib import Path

from sase.bead.config import load_config, save_config
from sase.bead.ids import IdGenerator, max_top_level_counter
from sase.bead.sync import (
    bead_state_is_clean,
    bead_store_write_lock,
    git_sync,
)


class BeadProjectStoreMixin:
    """Sync and config-refresh methods for ``BeadProject``."""

    beads_dir: Path
    _config: dict[str, object]
    _id_gen: IdGenerator
    _last_mutation_outcome: dict[str, object]
    _last_prefix_repair: tuple[str, str] | None
    _mutation_changed: bool

    def sync(self) -> None:
        """Stage bead state in git, exporting the compatibility projection first."""
        with bead_store_write_lock(self.beads_dir) as already_locked:
            if not (self.beads_dir / "events").is_dir():
                self._export()
            git_sync(self.beads_dir, already_locked=already_locked)

    def sync_is_clean(self) -> bool:
        """Check if canonical bead state has uncommitted changes."""
        return bead_state_is_clean(self.beads_dir)

    def _next_top_level_counter(self) -> int:
        """Return the next safe top-level counter for this bead store."""
        prefix = str(self._config.get("issue_prefix", "beads"))
        return max(
            self._id_gen.counter,
            max_top_level_counter(prefix, self.beads_dir) + 1,
        )

    def _export(self) -> None:
        """Export current state to JSONL through the required Rust binding."""
        from sase.core import bead_mutation_facade as rust_beads

        rust_beads.export_jsonl(self.beads_dir)
        self._refresh_config_after_mutation()

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
        self._refresh_config_after_mutation()
        self._last_prefix_repair = report

    def _record_mutation_outcome(self, outcome: dict[str, object]) -> None:
        """Accumulate honest core mutation results for commit gating."""
        self._last_mutation_outcome = outcome.copy()
        self._mutation_changed |= bool(outcome.get("changed", True))

    def _refresh_config_after_mutation(self) -> None:
        """Refresh lightweight config state after a Rust-owned mutation."""
        self._config = load_config(self.beads_dir)
        raw_counter = self._config.get("next_counter", 1)
        counter = raw_counter if isinstance(raw_counter, int) else int(str(raw_counter))
        self._id_gen = IdGenerator(
            str(self._config.get("issue_prefix", "beads")), counter
        )
