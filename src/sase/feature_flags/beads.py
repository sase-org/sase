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
from sase.bead.flag_fields import (
    FLAG_TASK_TYPE,
    FlagFields,
    flag_fields,
    is_flag_task_bead,
)
from sase.bead.model import Issue, IssueType, Status
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
    task_type: str = FLAG_TASK_TYPE
    kind: str | None = None
    title: str = ""
    created_at: str = ""
    created_by: str = ""


def _is_loaded_flag_bead(issue: Issue) -> bool:
    """Return whether *issue* belongs in the flag-bead snapshot list."""
    return is_flag_task_bead(issue)


def _flag_bead_snapshot_from_issue(issue: Issue) -> FlagBeadSnapshot:
    """Project one bead :class:`Issue` into a :class:`FlagBeadSnapshot`."""
    fields: FlagFields | None = flag_fields(issue)
    task_type = issue.task_type
    return FlagBeadSnapshot(
        id=issue.id,
        status=issue.status.value,
        key=None if fields is None else fields.key,
        remove_by_date=None if fields is None else fields.remove_by_date,
        remove_by_release=None if fields is None else fields.remove_by_release,
        task_type=task_type,
        kind=None if fields is None or not fields.kind else fields.kind,
        title=issue.title,
        created_at=issue.created_at,
        created_by=issue.created_by,
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
        issues = project.list_issues(issue_types=[IssueType.TASK])
    except Exception:  # noqa: BLE001 - doctor/CLI must stay read-only and best-effort.
        return None
    return tuple(
        _flag_bead_snapshot_from_issue(issue)
        for issue in issues
        if _is_loaded_flag_bead(issue)
    )


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
    *,
    key: str,
    kind: str,
    when_enabled: str,
    when_disabled: str,
    remove_when: str,
    remove_by_date: str,
    remove_by_release: str,
    title: str,
    description: str = "",
    size: str | None = None,
    cwd: Path | None = None,
) -> Issue:
    """Create the typed ``flag`` task bead for *key* and return it.

    Re-read the bead by key after the store mutation commits. A colliding
    id can be reminted on the commit/push path after ``create`` returns.
    """
    from sase.bead.attribution import resolve_bead_creator

    field_values = {
        "key": key,
        "kind": kind,
        "when_enabled": when_enabled,
        "when_disabled": when_disabled,
        "remove_when": remove_when,
        "remove_by_date": remove_by_date,
        "remove_by_release": remove_by_release,
    }

    existing = load_flag_bead_snapshots(cwd=cwd)
    if existing is not None:
        live = flag_bead_for_key(existing, key)
        if live is not None and live.status in LIVE_FLAG_STATUS_VALUES:
            raise FeatureFlagError(f"live flag bead {live.id} already owns key {key!r}")

    try:
        with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
            issue = mutation.project.create(
                title=title,
                issue_type=IssueType.TASK,
                description=description,
                size=size,
                created_by=resolve_bead_creator(issue_type=IssueType.TASK),
                task_type=FLAG_TASK_TYPE,
                task_type_fields=field_values,
            )
            mutation.commit(require_mutation_commit_message("create", [issue.id]))
    except (ValueError, RuntimeError, OSError) as exc:
        raise FeatureFlagError(str(exc)) from exc
    return _committed_flag_task_issue(key, cwd=cwd)


def _committed_flag_task_issue(key: str, *, cwd: Path | None) -> Issue:
    """Return the committed flag task bead for *key*, or fail if it vanished."""
    location = resolve_beads_location(cwd=cwd, require_existing=True)
    if location is not None and bead_store_exists(
        location.root, location.beads_dirname
    ):
        project = BeadProject(location.root, beads_dirname=location.beads_dirname)
        for candidate in project.list_issues(issue_types=[IssueType.TASK]):
            if (
                candidate.task_type == FLAG_TASK_TYPE
                and candidate.task_type_fields.get("key") == key
            ):
                return candidate
    raise FeatureFlagError(
        f"flag bead for {key!r} was not found after the store mutation committed"
    )


__all__ = [
    "FLAG_TASK_TYPE",
    "LIVE_FLAG_STATUS_VALUES",
    "FlagBeadSnapshot",
    "create_flag_bead",
    "flag_bead_for_id",
    "flag_bead_for_key",
    "load_flag_bead_snapshots",
]
