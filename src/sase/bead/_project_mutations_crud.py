"""Create/update mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize

if TYPE_CHECKING:
    from collections.abc import Callable


_NOTE_HEADER_RE = re.compile(r"^\[[^\]\n]+ · [^\]\n]+\] ")


class BeadProjectMutationCrudMixin:
    """Rust-backed create/update methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _last_prefix_repair: tuple[str, str] | None
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]
    _repair_stale_key_prefix: Callable[[], None]

    if TYPE_CHECKING:

        def show(self, issue_id: str) -> Issue: ...
        def resolve_id(self, issue_id: str) -> str: ...

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
        patch_name: str | int | None = None,
        patch_bug_id: str | int | None = None,
        changespec_name: str | int | None = "",
        changespec_bug_id: str | int | None = "",
        external_ref: str | int | None = "",
        model: str = "",
        size: PhaseSize | str | None = None,
        created_by: str | None = None,
        task_type: str = "",
        task_type_fields: dict[str, str] | None = None,
    ) -> Issue:
        """Create a new issue.

        If *parent_id* is provided the new issue ID is hierarchical:
        ``<parent_id>.<N>`` where *N* is the next available integer.
        Otherwise the global counter-based ID generator is used.
        """
        from sase.core import bead_mutation_facade as rust_beads

        self._last_prefix_repair = None
        if parent_id is not None:
            parent_id = self.resolve_id(parent_id)
        else:
            self._repair_stale_key_prefix()
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
            patch_name=patch_name,
            patch_bug_id=patch_bug_id,
            changespec_name=changespec_name,
            changespec_bug_id=changespec_bug_id,
            external_ref=external_ref,
            model=model,
            size=size,
            created_by=created_by,
            task_type=task_type,
            task_type_fields=task_type_fields or {},
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def update(self, issue_id: str, **fields: Any) -> Issue:
        """Update fields on an issue."""
        if "is_ready_to_work" in fields:
            raise ValueError(
                "is_ready_to_work cannot be set via update(); "
                "use mark_ready_to_work() instead."
            )
        from sase.core import bead_mutation_facade as rust_beads

        issue_id = self.resolve_id(issue_id)
        notes_update = fields.pop("notes", None)
        try:
            old_issue: Issue | None = self.show(issue_id)
        except KeyError:
            old_issue = None
        if old_issue is not None:
            fields = _normalize_patch_fields(fields)
            _validate_issue_update(old_issue, fields)
        outcomes: list[dict[str, object]] = []
        now = self._current_time()
        if fields:
            issue, outcome = rust_beads.update(
                self.beads_dir, issue_id, **fields, now=now
            )
            outcomes.append(outcome)
        else:
            issue = old_issue if old_issue is not None else self.show(issue_id)
        if notes_update is not None:
            entry = _note_append_entry(issue.notes_text, notes_update)
            if entry is not None:
                issue, outcome = rust_beads.append_note(
                    self.beads_dir,
                    issue_id,
                    entry,
                    now=now,
                )
                outcomes.append(outcome)
        self._record_mutation_outcome(_combine_mutation_outcomes("update", outcomes))
        self._refresh_db_from_jsonl()
        return issue

    def update_many(self, issue_ids: list[str], **fields: Any) -> list[Issue]:
        """Apply the same field changes to multiple issues in one mutation.

        Every ID is resolved and validated against its pre-batch issue before
        the atomic Rust-backed mutation runs, so an unknown ID or an invalid
        field value leaves every named issue untouched.
        """
        if "is_ready_to_work" in fields:
            raise ValueError(
                "is_ready_to_work cannot be set via update(); "
                "use mark_ready_to_work() instead."
            )
        from sase.core import bead_mutation_facade as rust_beads

        resolved_ids = [self.resolve_id(issue_id) for issue_id in issue_ids]
        notes_update = fields.pop("notes", None)
        normalized_fields = _normalize_patch_fields(fields)
        old_issues: dict[str, Issue] = {}
        for issue_id in resolved_ids:
            try:
                old_issue: Issue | None = self.show(issue_id)
            except KeyError:
                old_issue = None
            if old_issue is not None:
                old_issues[issue_id] = old_issue
            if old_issue is not None:
                _validate_issue_update(old_issue, normalized_fields)
        outcomes: list[dict[str, object]] = []
        now = self._current_time()
        if normalized_fields:
            issues, outcome = rust_beads.update_many(
                self.beads_dir,
                resolved_ids,
                **normalized_fields,
                now=now,
            )
            outcomes.append(outcome)
            issue_by_id = {issue.id: issue for issue in issues}
        else:
            issue_by_id = {
                issue_id: old_issues.get(issue_id, self.show(issue_id))
                for issue_id in resolved_ids
            }
        if notes_update is not None:
            for issue_id in resolved_ids:
                issue = issue_by_id[issue_id]
                entry = _note_append_entry(issue.notes_text, notes_update)
                if entry is None:
                    continue
                issue, outcome = rust_beads.append_note(
                    self.beads_dir,
                    issue_id,
                    entry,
                    now=now,
                )
                outcomes.append(outcome)
                issue_by_id[issue_id] = issue
        issues = [issue_by_id[issue_id] for issue_id in resolved_ids]
        self._record_mutation_outcome(_combine_mutation_outcomes("update", outcomes))
        self._refresh_db_from_jsonl()
        return issues


def _combine_mutation_outcomes(
    operation: str,
    outcomes: list[dict[str, object]],
) -> dict[str, object]:
    if not outcomes:
        return {"operation": operation, "issue_ids": []}
    issue_ids: list[str] = []
    reopened_ancestor_ids: list[str] = []
    for outcome in outcomes:
        _extend_unique(issue_ids, outcome.get("issue_ids"))
        _extend_unique(reopened_ancestor_ids, outcome.get("reopened_ancestor_ids"))
    combined = outcomes[-1].copy()
    combined["operation"] = operation
    combined["issue_ids"] = issue_ids
    if reopened_ancestor_ids:
        combined["reopened_ancestor_ids"] = reopened_ancestor_ids
    return combined


def _extend_unique(target: list[str], raw: object) -> None:
    if not isinstance(raw, list):
        return
    for item in raw:
        if not isinstance(item, str) or item in target:
            continue
        target.append(item)


def _normalize_notes_text(value: object) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _notes_body_projection(value: str) -> str:
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", value) if item.strip()]
    return "\n\n".join(
        _NOTE_HEADER_RE.sub("", paragraph, count=1) for paragraph in paragraphs
    )


def _note_append_entry(current_notes: str, requested_notes: object) -> str | None:
    requested = _normalize_notes_text(requested_notes)
    current = _normalize_notes_text(current_notes)
    if not requested:
        if current:
            raise ValueError(
                "notes cannot be replaced via update(); use append_note() instead."
            )
        return None
    if not current:
        return requested
    for baseline in (current, _notes_body_projection(current)):
        if requested == baseline:
            return None
        if requested.startswith(baseline):
            suffix = requested[len(baseline) :].strip()
            return suffix or None
    return requested


def _optional_text(value: str | int | None) -> str:
    return "" if value is None else str(value)


def _validate_flag_threshold_field_update(issue: Issue, raw: object) -> None:
    """Allow only the two data-role flag thresholds to change on a flag task."""
    from sase.bead.flag_fields import is_flag_task_bead

    if not is_flag_task_bead(issue):
        raise ValueError(
            "task_type is immutable; close this bead and recreate it "
            "with -T 'task(<slug>)'"
        )
    if not isinstance(raw, dict):
        raise ValueError("task_type_fields must be a mapping")
    new_fields = {str(key): str(value) for key, value in raw.items()}
    allowed = {"remove_by_date", "remove_by_release"}
    old_rest = {
        key: value
        for key, value in issue.task_type_fields.items()
        if key not in allowed
    }
    new_rest = {key: value for key, value in new_fields.items() if key not in allowed}
    if old_rest != new_rest:
        raise ValueError(
            "only remove_by_date and remove_by_release can be updated on a flag bead"
        )
    if "remove_by_date" not in new_fields or "remove_by_release" not in new_fields:
        raise ValueError(
            "flag threshold update requires remove_by_date and remove_by_release"
        )


def _normalize_patch_fields(
    fields: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(fields)
    for canonical_name, legacy_name in (
        ("patch_name", "changespec_name"),
        ("patch_bug_id", "changespec_bug_id"),
    ):
        canonical_value = normalized.pop(canonical_name, None)
        if canonical_value is None:
            continue
        legacy_value = _optional_text(normalized.get(legacy_name))
        canonical_text = _optional_text(canonical_value)
        if canonical_text and legacy_value and canonical_text != legacy_value:
            raise ValueError(f"{canonical_name} conflicts with {legacy_name}")
        normalized[legacy_name] = canonical_text or legacy_value
    for name in ("changespec_name", "changespec_bug_id", "external_ref"):
        if name in normalized:
            normalized[name] = _optional_text(normalized[name])
    return normalized


def _validate_issue_update(issue: Issue, fields: dict[str, Any]) -> None:
    if "task_type" in fields:
        raise ValueError(
            "task_type is immutable; close this bead and recreate it "
            "with -T 'task(<slug>)'"
        )
    if "task_type_fields" in fields:
        _validate_flag_threshold_field_update(issue, fields["task_type_fields"])
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
