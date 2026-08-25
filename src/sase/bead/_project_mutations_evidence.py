"""Note and +1 evidence mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead._project_mutations_shared import combine_mutation_outcomes
from sase.bead.model import Issue

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectMutationEvidenceMixin:
    """Rust-backed note/+1 methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]

    if TYPE_CHECKING:

        def show(self, issue_id: str) -> Issue: ...
        def resolve_id(self, issue_id: str) -> str: ...

    def append_note(
        self,
        issue_id: str,
        entry: str,
        *,
        author: str | None = None,
    ) -> Issue:
        """Append one attributed entry to an issue's notes."""
        from sase.core import bead_mutation_facade as rust_beads

        issue_id = self.resolve_id(issue_id)
        issue, outcome = rust_beads.append_note(
            self.beads_dir,
            issue_id,
            entry,
            author=author,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def edit_note(
        self,
        issue_id: str,
        ordinal: int,
        text: str,
        *,
        author: str | None = None,
    ) -> Issue:
        """Rewrite note ``#ordinal`` (1-based, per `sase bead show`) with new text."""
        from sase.core import bead_mutation_facade as rust_beads

        issue_id = self.resolve_id(issue_id)
        note_id = _resolve_note_ordinal(self.show(issue_id), ordinal)
        issue, outcome = rust_beads.edit_note(
            self.beads_dir,
            issue_id,
            note_id,
            text,
            author=author,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def remove_note(
        self,
        issue_id: str,
        ordinal: int,
        *,
        author: str | None = None,
    ) -> Issue:
        """Retract note ``#ordinal`` (1-based, per `sase bead show`)."""
        from sase.core import bead_mutation_facade as rust_beads

        issue_id = self.resolve_id(issue_id)
        note_id = _resolve_note_ordinal(self.show(issue_id), ordinal)
        issue, outcome = rust_beads.remove_note(
            self.beads_dir,
            issue_id,
            note_id,
            author=author,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def append_note_many(
        self,
        issue_ids: list[str],
        entry: str,
        *,
        author: str | None = None,
    ) -> list[Issue]:
        """Append one attributed entry to each unique issue, preserving result order."""
        from sase.core import bead_mutation_facade as rust_beads

        resolved_ids = [self.resolve_id(issue_id) for issue_id in issue_ids]
        unique_ids = list(dict.fromkeys(resolved_ids))
        for issue_id in unique_ids:
            self.show(issue_id)
        now = self._current_time()
        issue_by_id: dict[str, Issue] = {}
        outcomes: list[dict[str, object]] = []
        for issue_id in unique_ids:
            issue, outcome = rust_beads.append_note(
                self.beads_dir,
                issue_id,
                entry,
                author=author,
                now=now,
            )
            issue_by_id[issue_id] = issue
            outcomes.append(outcome)
        self._record_mutation_outcome(combine_mutation_outcomes("update", outcomes))
        self._refresh_db_from_jsonl()
        return [issue_by_id[issue_id] for issue_id in resolved_ids]

    def plus_one(
        self,
        issue_id: str,
        note: str,
        *,
        reporter: str,
        refs: list[str] | tuple[str, ...] = (),
        observed_since: str | None = None,
    ) -> tuple[Issue, bool]:
        """Record one independently attributed +1 on a task bead."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.plus_one(
            self.beads_dir,
            issue_id,
            reporter=reporter,
            note=note,
            refs=refs,
            now=self._current_time(),
            observed_since=observed_since,
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])


def _resolve_note_ordinal(issue: Issue, ordinal: int) -> str:
    """Resolve a 1-based note ordinal (as shown by `sase bead show`) to its note id."""
    if ordinal < 1 or ordinal > len(issue.notes):
        count = len(issue.notes)
        noun = "note" if count == 1 else "notes"
        raise ValueError(
            f"note #{ordinal} does not exist on {issue.id} ({count} {noun} present)"
        )
    return issue.notes[ordinal - 1].id
