"""Snooze mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import Issue

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectMutationSnoozeMixin:
    """Rust-backed snooze methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]

    if TYPE_CHECKING:

        def resolve_id(self, issue_id: str) -> str: ...

    def snooze(
        self,
        issue_id: str,
        *,
        until: str,
        actor: str,
        plus_ones: int | None = None,
        reason: str = "",
    ) -> Issue:
        """Defer one task bead until ``until``, or until a +1 threshold."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.snooze(
            self.beads_dir,
            self.resolve_id(issue_id),
            until=until,
            plus_ones=plus_ones,
            reason=reason,
            actor=actor,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def cancel_snooze(self, issue_id: str, *, actor: str) -> Issue:
        """Undo a snooze, returning the bead to ``ready``."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.cancel_snooze(
            self.beads_dir,
            self.resolve_id(issue_id),
            actor=actor,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue
