"""Link and dependency mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import Dependency, Issue

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectMutationLinksMixin:
    """Rust-backed link/dependency methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]

    def add_link(
        self,
        issue_id: str,
        target_ref: str,
        relation: str,
        description: str,
        *,
        origin: str = "manual",
    ) -> Issue:
        """Record one typed outbound link on a bead."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.add_link(
            self.beads_dir,
            issue_id,
            target_ref,
            relation,
            description,
            origin=origin,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def remove_link(
        self,
        issue_id: str,
        target_ref: str,
        *,
        relation: str | None = None,
    ) -> Issue:
        """Remove one typed outbound link, or every edge to *target_ref*."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.remove_link(
            self.beads_dir,
            issue_id,
            target_ref,
            relation=relation,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def add_dependency(self, issue_id: str, depends_on_id: str) -> Dependency:
        """Add a dependency: issue_id depends on depends_on_id."""
        from sase.core import bead_mutation_facade as rust_beads

        dep, outcome = rust_beads.add_dependency(
            self.beads_dir, issue_id, depends_on_id, now=self._current_time()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return dep

    def remove_dependencies(
        self, issue_id: str, depends_on_ids: list[str]
    ) -> list[Dependency]:
        """Remove dependency edges from issue_id to depends_on_ids."""
        from sase.core import bead_mutation_facade as rust_beads

        dependencies, outcome = rust_beads.remove_dependencies(
            self.beads_dir, issue_id, depends_on_ids, now=self._current_time()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return dependencies
