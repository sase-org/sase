"""Mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead._project_types import EpicPreclaimRollback
from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectMutationMixin:
    """Rust-backed mutation methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]

    if TYPE_CHECKING:

        def show(self, issue_id: str) -> Issue: ...

    def create(
        self,
        title: str,
        issue_type: IssueType,
        parent_id: str | None = None,
        *,
        description: str = "",
        notes: str = "",
        design: str = "",
        refs: list[str] | tuple[str, ...] = (),
        assignee: str = "",
        tier: BeadTier | str | None = None,
        changespec_name: str | int | None = "",
        changespec_bug_id: str | int | None = "",
        model: str = "",
        size: PhaseSize | str | None = None,
        created_by: str | None = None,
    ) -> Issue:
        """Create a new issue.

        If *parent_id* is provided the new issue ID is hierarchical:
        ``<parent_id>.<N>`` where *N* is the next available integer.
        Otherwise the global counter-based ID generator is used.
        """
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.create(
            self.beads_dir,
            title=title,
            issue_type=issue_type,
            tier=tier,
            parent_id=parent_id,
            description=description,
            notes=notes,
            design=design,
            refs=refs,
            assignee=assignee,
            changespec_name=changespec_name,
            changespec_bug_id=changespec_bug_id,
            model=model,
            size=size,
            created_by=created_by,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def update(self, issue_id: str, **fields: str | int | None) -> Issue:
        """Update fields on an issue."""
        if "is_ready_to_work" in fields:
            raise ValueError(
                "is_ready_to_work cannot be set via update(); "
                "use mark_ready_to_work() instead."
            )
        from sase.core import bead_mutation_facade as rust_beads

        try:
            old_issue: Issue | None = self.show(issue_id)
        except KeyError:
            old_issue = None
        if old_issue is not None:
            fields = _normalize_changespec_fields(fields)
            _validate_issue_update(old_issue, fields)
        issue, outcome = rust_beads.update(
            self.beads_dir, issue_id, **fields, now=self._current_time()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def append_note(
        self,
        issue_id: str,
        entry: str,
        *,
        author: str | None = None,
    ) -> Issue:
        """Append one attributed entry to an issue's notes."""
        from sase.core import bead_mutation_facade as rust_beads

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

    def claim_for_agent_launch(self, bead_id: str, agent_name: str) -> Issue:
        """Atomically claim one non-closed bead for an agent launch."""
        issue, _changed = self.claim_for_agent_launch_outcome(bead_id, agent_name)
        return issue

    def claim_for_agent_launch_outcome(
        self, bead_id: str, agent_name: str
    ) -> tuple[Issue, bool]:
        """Claim for launch and return whether core persisted a transition."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.claim_for_agent_launch(
            self.beads_dir,
            bead_id,
            agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome.get("changed", True))

    def claim_for_agent_wait(self, bead_id: str, agent_name: str) -> tuple[Issue, bool]:
        """Reserve an open bead while its owning agent waits to launch."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.claim_for_agent_wait(
            self.beads_dir,
            bead_id,
            agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])

    def release_agent_claim(self, bead_id: str, agent_name: str) -> tuple[Issue, bool]:
        """Release a waiting claim when it is still held by *agent_name*."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.release_agent_claim(
            self.beads_dir,
            bead_id,
            agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])

    def preclaim_epic_work(
        self,
        epic_id: str,
        assignments: list[tuple[str, str]],
        land_agent_name: str,
    ) -> tuple[EpicPreclaimRollback, ...]:
        """Preassign one rendered epic work plan and return rollback state."""
        from sase.core import bead_mutation_facade as rust_beads

        _issues, outcome = rust_beads.preclaim_epic_work(
            self.beads_dir,
            epic_id,
            assignments=assignments,
            land_agent_name=land_agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return tuple(
            EpicPreclaimRollback(
                bead_id=str(record["bead_id"]),
                status=Status(str(record["status"])),
                assignee=str(record.get("assignee", "")),
            )
            for record in outcome.get("rollback_preclaims", [])
        )

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

        updated, outcome = rust_beads.unmark_ready_to_work(
            self.beads_dir, epic_id, now=self._current_time()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return updated

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

    def reproject_from_events(self) -> dict[str, object]:
        """Rewrite issues.jsonl from the canonical event streams."""
        from sase.core import bead_mutation_facade as rust_beads

        outcome = rust_beads.export_jsonl(self.beads_dir)
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return outcome


def _optional_text(value: str | int | None) -> str:
    return "" if value is None else str(value)


def _normalize_changespec_fields(
    fields: dict[str, str | int | None],
) -> dict[str, str | int | None]:
    normalized = dict(fields)
    for name in ("changespec_name", "changespec_bug_id"):
        if name in normalized:
            normalized[name] = _optional_text(normalized[name])
    return normalized


def _validate_issue_update(issue: Issue, fields: dict[str, str | int | None]) -> None:
    if "changespec_name" not in fields and "changespec_bug_id" not in fields:
        return
    candidate = replace(
        issue,
        changespec_name=(
            _optional_text(fields["changespec_name"])
            if "changespec_name" in fields
            else issue.changespec_name
        ),
        changespec_bug_id=(
            _optional_text(fields["changespec_bug_id"])
            if "changespec_bug_id" in fields
            else issue.changespec_bug_id
        ),
    )
    candidate.validate()
