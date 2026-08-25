"""Close/open/remove/ready-flag mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import Issue, Resolution

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectMutationLifecycleMixin:
    """Rust-backed close/open/remove/ready-flag methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]

    if TYPE_CHECKING:

        def resolve_id(self, issue_id: str) -> str: ...

    def close(
        self,
        issue_ids: list[str],
        reason: str | None = None,
        resolution: Resolution | str | None = None,
        force: bool = False,
        note: str | None = None,
        author: str | None = None,
    ) -> list[Issue]:
        """Close one or more issues.

        Descendants must already be closed unless ``force`` explicitly sweeps
        them with a non-done resolution and reason. When ``note`` is provided,
        append it to every explicitly listed issue in the same mutation.
        """
        from sase.core import bead_mutation_facade as rust_beads

        issue_ids = [self.resolve_id(issue_id) for issue_id in issue_ids]
        closed, outcome = rust_beads.close(
            self.beads_dir,
            issue_ids,
            reason=reason,
            resolution=resolution,
            force=force,
            note=note,
            author=author,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return closed

    def open(self, issue_id: str) -> tuple[Issue, list[Issue]]:
        """Reopen an issue and every closed ancestor above it."""
        from sase.core import bead_mutation_facade as rust_beads
        from sase.core.bead_wire import issues_from_list

        issue_id = self.resolve_id(issue_id)
        issue, outcome = rust_beads.open_issue(
            self.beads_dir,
            issue_id,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        reopened_ancestors = issues_from_list(outcome.get("issues", []))
        self._refresh_db_from_jsonl()
        return issue, reopened_ancestors

    def remove(self, issue_id: str) -> list[Issue]:
        """Delete an issue and all its children.

        Returns the list of issues that were removed (the target plus any
        cascade-deleted children), ordered children-first.
        Raises KeyError if the issue does not exist.
        """
        from sase.core import bead_mutation_facade as rust_beads

        removed, outcome = rust_beads.remove(self.beads_dir, issue_id)
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return removed

    def remove_many(self, issue_ids: list[str]) -> list[Issue]:
        """Atomically delete one or more issues and their descendants.

        Every requested ID is validated before mutation. The returned issues
        are unique even when requests overlap or repeat.
        """
        from sase.core import bead_mutation_facade as rust_beads

        issue_ids = [self.resolve_id(issue_id) for issue_id in issue_ids]
        removed, outcome = rust_beads.remove_many(self.beads_dir, issue_ids)
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return removed

    def mark_ready_to_work(self, epic_id: str) -> Issue:
        """Flip the epic plan's is_ready_to_work flag to True.

        Raises KeyError if the issue does not exist, NotAPlanError if it
        is not a plan, and AlreadyReadyError if the flag is already set.
        """
        from sase.core import bead_mutation_facade as rust_beads

        epic_id = self.resolve_id(epic_id)
        updated, outcome = rust_beads.mark_ready_to_work(
            self.beads_dir, epic_id, now=self._current_time()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return updated

    def unmark_ready_to_work(self, epic_id: str) -> Issue:
        """Reset is_ready_to_work=False on an epic plan bead.

        Used by ``sase bead work`` to roll the flag back when the downstream
        agent launch fails after the flag has already been flipped. The flip
        itself stays a one-way mutator via :meth:`mark_ready_to_work` — this
        is the explicit recovery hatch.

        Raises KeyError if the issue does not exist.
        """
        from sase.core import bead_mutation_facade as rust_beads

        epic_id = self.resolve_id(epic_id)
        updated, outcome = rust_beads.unmark_ready_to_work(
            self.beads_dir, epic_id, now=self._current_time()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return updated

    def reproject_from_events(self) -> dict[str, object]:
        """Rewrite issues.jsonl from the canonical event streams."""
        from sase.core import bead_mutation_facade as rust_beads

        outcome = rust_beads.export_jsonl(self.beads_dir)
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return outcome
