"""Note and +1 evidence mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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

    def append_note(
        self,
        issue_id: str,
        entry: str,
        *,
        author: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> Issue:
        """Append one attributed entry to an issue's notes."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.append_note(
            self.beads_dir,
            issue_id,
            entry,
            author=author,
            now=self._current_time(),
            attachments=attachments,
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
        attachments: list[dict[str, Any]] | None = None,
    ) -> Issue:
        """Rewrite note ``#ordinal`` (1-based, per `sase bead show`) with new text.

        ``attachments`` is ``None`` to keep the note's current manifest or a
        list (possibly empty) to replace it.
        """
        from sase.core import bead_mutation_facade as rust_beads

        # The ordinal-to-note-ID mapping needs the current notes (one
        # authoring read); the edit binding resolves the raw bead ID.
        note_id = _resolve_note_ordinal(self.show(issue_id), ordinal)
        issue, outcome = rust_beads.edit_note(
            self.beads_dir,
            issue_id,
            note_id,
            text,
            author=author,
            now=self._current_time(),
            attachments=attachments,
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

        # The ordinal-to-note-ID mapping needs the current notes (one
        # authoring read); the remove binding resolves the raw bead ID.
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
        attachments: list[dict[str, Any]] | None = None,
    ) -> list[Issue]:
        """Append one attributed entry to each unique issue, preserving result order.

        Raw IDs pass straight into the append binding, which resolves them
        inside each locked load. The pre-append existence shows are gone:
        the binding reports unknown IDs itself.
        """
        from sase.core import bead_mutation_facade as rust_beads

        unique_ids = list(dict.fromkeys(issue_ids))
        now = self._current_time()
        issue_by_id: dict[str, Issue] = {}
        resolved_by_raw: dict[str, str] = {}
        outcomes: list[dict[str, object]] = []
        for issue_id in unique_ids:
            if "-" in issue_id and issue_id in issue_by_id:
                # A full ID spelling of an already-appended bead: the
                # earlier append resolved it, so collapse the duplicate.
                resolved_by_raw[issue_id] = issue_id
                continue
            issue, outcome = rust_beads.append_note(
                self.beads_dir,
                issue_id,
                entry,
                author=author,
                now=now,
                attachments=attachments,
            )
            issue_by_id[issue.id] = issue
            resolved_by_raw[issue_id] = issue.id
            outcomes.append(outcome)
        self._record_mutation_outcome(combine_mutation_outcomes("update", outcomes))
        self._refresh_db_from_jsonl()
        return [issue_by_id[resolved_by_raw[raw_id]] for raw_id in issue_ids]

    def plus_one(
        self,
        issue_id: str,
        note: str,
        *,
        reporter: str,
        refs: list[str] | tuple[str, ...] = (),
        observed_since: str | None = None,
        note_attachments: list[dict[str, Any]] | None = None,
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
            note_attachments=note_attachments,
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
