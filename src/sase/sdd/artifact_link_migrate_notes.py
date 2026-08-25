"""Scan bead notes for ``RELATED:`` rows and convert them to typed links."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Any

from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.sdd.artifact_link_beads import bead_source_ref

_RELATED_LINE_RE = re.compile(r"^RELATED:\s*(?P<targets>.+?)\s*[—–]\s*(?P<why>.+)\s*$")
_MIGRATED_LINE_RE = re.compile(r"^MIGRATED:\s*linked as (?P<marker>\S+)\s*$")
_BEAD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_SHA_RE = re.compile(r"\b([0-9a-fA-F]{40})\b")
_STITCH_RE = re.compile(
    r"\b(?:stitch|commit):(?P<repo>[A-Za-z0-9._-]+)@(?P<sha>[0-9a-fA-F]{7,40})\b",
    re.IGNORECASE,
)
_MAX_LINK_DESCRIPTION_LENGTH = 240


@dataclass(frozen=True)
class RelatedNoteConversion:
    """One parseable ``RELATED:`` line that can become typed ``related`` edges."""

    issue_id: str
    line: str
    targets: tuple[str, ...]
    why: str


@dataclass(frozen=True)
class RelatedNoteWorkItem:
    """One ``RELATED:`` line that needs a human, not a guess."""

    issue_id: str
    line: str
    reason: str


@dataclass(frozen=True)
class RelatedNoteMigrationPlan:
    """Dry-run report for ``sase artifact link migrate-notes``."""

    conversions: tuple[RelatedNoteConversion, ...]
    worklist: tuple[RelatedNoteWorkItem, ...]
    scanned_notes: int
    scanned_beads: int


def plan_related_note_migration(issues: Sequence[Issue]) -> RelatedNoteMigrationPlan:
    """Scan notes without writing events or ``MIGRATED:`` follow-ups."""

    conversions: list[RelatedNoteConversion] = []
    worklist: list[RelatedNoteWorkItem] = []
    scanned_notes = 0
    known_ids = {issue.id for issue in issues}
    for issue in issues:
        migrated_markers = _migrated_markers(issue.notes_text)
        for line in _related_lines(issue.notes_text):
            scanned_notes += 1
            conversion, work_item = _classify_related_line(issue.id, line, known_ids)
            if conversion is not None:
                remaining_targets = tuple(
                    target
                    for target in conversion.targets
                    if _migrated_marker(target) not in migrated_markers
                )
                if not remaining_targets:
                    continue
                if remaining_targets != conversion.targets:
                    conversion = RelatedNoteConversion(
                        issue_id=conversion.issue_id,
                        line=conversion.line,
                        targets=remaining_targets,
                        why=conversion.why,
                    )
            if conversion is not None:
                conversions.append(conversion)
            if work_item is not None:
                worklist.append(work_item)
    return RelatedNoteMigrationPlan(
        conversions=tuple(conversions),
        worklist=tuple(worklist),
        scanned_notes=scanned_notes,
        scanned_beads=len(issues),
    )


def apply_related_note_migration(
    project: BeadProject,
    plan: RelatedNoteMigrationPlan,
    *,
    origin: str = "migrated",
) -> dict[str, Any]:
    """Write ``related`` events and ``MIGRATED:`` notes for one dry-run plan."""

    converted = 0
    notes = 0
    for item in plan.conversions:
        for target in item.targets:
            project.add_link(
                item.issue_id,
                target,
                "related",
                item.why,
                origin=origin,
            )
            converted += 1
            suffix = target.removeprefix("bead:")
            project.append_note(item.issue_id, f"MIGRATED: linked as related/{suffix}")
            notes += 1
    return {"converted": converted, "migrated_notes": notes}


def _related_lines(notes: str) -> tuple[str, ...]:
    found: list[str] = []
    for raw in notes.splitlines():
        line = raw.strip()
        marker = line.find("RELATED:")
        if marker < 0:
            continue
        found.append(line[marker:])
    return tuple(found)


def _classify_related_line(
    issue_id: str,
    line: str,
    known_ids: set[str],
) -> tuple[RelatedNoteConversion | None, RelatedNoteWorkItem | None]:
    match = _RELATED_LINE_RE.match(line)
    if match is None:
        return None, RelatedNoteWorkItem(
            issue_id=issue_id,
            line=line,
            reason="does not match RELATED: <id>[, <id>] — <why>",
        )
    why = _trim_description(match.group("why").strip())
    if not why:
        return None, RelatedNoteWorkItem(
            issue_id=issue_id, line=line, reason="empty rationale"
        )
    raw_targets = [part.strip() for part in match.group("targets").split(",")]
    targets: list[str] = []
    for raw in raw_targets:
        resolved = _resolve_related_target(raw, known_ids)
        if resolved is None:
            return None, RelatedNoteWorkItem(
                issue_id=issue_id,
                line=line,
                reason=f"unparseable target {raw!r}",
            )
        if resolved == bead_source_ref(issue_id):
            return None, RelatedNoteWorkItem(
                issue_id=issue_id,
                line=line,
                reason="self-link",
            )
        targets.append(resolved)
    if not targets:
        return None, RelatedNoteWorkItem(
            issue_id=issue_id, line=line, reason="no targets"
        )
    return (
        RelatedNoteConversion(
            issue_id=issue_id, line=line, targets=tuple(targets), why=why
        ),
        None,
    )


def _resolve_related_target(raw: str, known_ids: set[str]) -> str | None:
    token = raw.strip().lstrip("@")
    if not token:
        return None
    stitch = _STITCH_RE.search(token)
    if stitch is not None:
        return f"stitch:{stitch.group('repo')}@{stitch.group('sha').lower()}"
    if token.startswith("bead:"):
        bead_id = token.partition(":")[2]
        if bead_id in known_ids or _BEAD_ID_RE.match(bead_id):
            return f"bead:{bead_id}"
        return None
    if token in known_ids:
        return f"bead:{token}"
    if _SHA_RE.fullmatch(token):
        return None
    if _BEAD_ID_RE.match(token):
        return f"bead:{token}"
    return None


def _migrated_markers(notes: str) -> frozenset[str]:
    markers: set[str] = set()
    for raw in notes.splitlines():
        line = raw.strip()
        marker = line.find("MIGRATED:")
        if marker < 0:
            continue
        match = _MIGRATED_LINE_RE.match(line[marker:])
        if match is not None:
            markers.add(match.group("marker"))
    return frozenset(markers)


def _migrated_marker(target_ref: str) -> str:
    if target_ref.startswith("bead:"):
        target_ref = target_ref.removeprefix("bead:")
    return f"related/{target_ref}"


def _trim_description(value: str) -> str:
    if len(value) <= _MAX_LINK_DESCRIPTION_LENGTH:
        return value
    return value[: _MAX_LINK_DESCRIPTION_LENGTH - 3].rstrip() + "..."


__all__ = [
    "RelatedNoteConversion",
    "RelatedNoteMigrationPlan",
    "RelatedNoteWorkItem",
    "apply_related_note_migration",
    "plan_related_note_migration",
]
