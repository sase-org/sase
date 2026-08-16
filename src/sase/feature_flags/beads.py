"""Read and create the dedicated flag beads that own ``remove_by``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_exists,
    bead_store_mutation,
    resolve_beads_location,
)
from sase.bead.model import FlagRecord, Issue, IssueType, Status
from sase.bead.mutation_commit import require_mutation_commit_message
from sase.bead.project import BeadProject
from sase.feature_flags.models import FeatureFlagError


_LIVE_FLAG_STATUSES = frozenset(
    {
        Status.OPEN,
        Status.CLAIMED,
        Status.READY,
        Status.SNOOZED,
        Status.IN_PROGRESS,
    }
)
LIVE_FLAG_STATUS_VALUES = frozenset(status.value for status in _LIVE_FLAG_STATUSES)


@dataclass(frozen=True)
class FlagBeadSnapshot:
    """The bead fields the flag CLI and doctor need, without a live store."""

    id: str
    status: str
    key: str | None
    remove_by_date: str | None = None
    remove_by_release: str | None = None
    issue_type: str = "flag"
    title: str = ""


def _flag_bead_snapshot_from_issue(issue: Issue) -> FlagBeadSnapshot:
    """Project one bead :class:`Issue` into a :class:`FlagBeadSnapshot`."""
    record = issue.flag
    return FlagBeadSnapshot(
        id=issue.id,
        status=issue.status.value,
        key=None if record is None else record.key,
        remove_by_date=None if record is None else record.remove_by_date,
        remove_by_release=None if record is None else record.remove_by_release,
        issue_type=issue.issue_type.value,
        title=issue.title,
    )


def load_flag_bead_snapshots(
    cwd: Path | None = None,
) -> tuple[FlagBeadSnapshot, ...] | None:
    """Return this checkout's flag beads, or ``None`` when no store is readable."""
    location = resolve_beads_location(cwd=cwd, require_existing=True)
    if location is None or not bead_store_exists(location.root, location.beads_dirname):
        return None
    try:
        project = BeadProject(location.root, beads_dirname=location.beads_dirname)
        issues = project.list_issues(issue_types=[IssueType.FLAG])
    except Exception:  # noqa: BLE001 - doctor/CLI must stay read-only and best-effort.
        return None
    return tuple(_flag_bead_snapshot_from_issue(issue) for issue in issues)


def flag_bead_for_key(
    beads: tuple[FlagBeadSnapshot, ...] | None,
    key: str,
) -> FlagBeadSnapshot | None:
    """Return the flag bead whose ``flag.key`` is *key*, if any."""
    if beads is None:
        return None
    for bead in beads:
        if bead.key == key:
            return bead
    return None


def flag_bead_for_id(
    beads: tuple[FlagBeadSnapshot, ...] | None,
    bead_id: str,
) -> FlagBeadSnapshot | None:
    """Return the snapshot with *bead_id*, if it is present."""
    if beads is None:
        return None
    for bead in beads:
        if bead.id == bead_id:
            return bead
    return None


def create_flag_bead(
    record: FlagRecord,
    *,
    title: str,
    description: str = "",
    size: str | None = None,
    cwd: Path | None = None,
) -> Issue:
    """Create the dedicated removal bead for *record* and return it."""
    from sase.bead.attribution import resolve_bead_creator

    existing = load_flag_bead_snapshots(cwd=cwd)
    if existing is not None:
        live = flag_bead_for_key(existing, record.key)
        if live is not None and live.status in LIVE_FLAG_STATUS_VALUES:
            raise FeatureFlagError(
                f"live flag bead {live.id} already owns key {record.key!r}"
            )

    try:
        with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
            issue = mutation.project.create(
                title=title,
                issue_type=IssueType.FLAG,
                description=description,
                flag=record,
                size=size,
                created_by=resolve_bead_creator(issue_type=IssueType.FLAG),
            )
            mutation.commit(require_mutation_commit_message("create", [issue.id]))
    except (ValueError, RuntimeError, OSError) as exc:
        raise FeatureFlagError(str(exc)) from exc
    return issue


def flag_record_from_snapshot(bead: FlagBeadSnapshot) -> FlagRecord | None:
    """Return a :class:`FlagRecord` when *bead* carries both thresholds."""
    if not bead.key or not bead.remove_by_date or not bead.remove_by_release:
        return None
    return FlagRecord(
        key=bead.key,
        remove_by_date=bead.remove_by_date,
        remove_by_release=bead.remove_by_release,
    )


__all__ = [
    "LIVE_FLAG_STATUS_VALUES",
    "FlagBeadSnapshot",
    "create_flag_bead",
    "flag_bead_for_id",
    "flag_bead_for_key",
    "flag_record_from_snapshot",
    "load_flag_bead_snapshots",
]
