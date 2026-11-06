"""Python facade over the journaled ACE-run trash owner in ``sase_core``.

Shared safety and policy logic lives in the Rust core
(:mod:`sase_core::agent_artifact_run_trash`); this module sequences effects:
it builds the quarantine request from a fresh retention plan, calls the
bindings, and keeps the agent artifact index consistent afterwards.

Index follow-ups never undo the moves: after a quarantine the moved dirs are
deindexed, and after any restore (including restores during a purge) the
restored dirs are re-indexed. Index failures are reported in the result, never
swallowed and never rolled back.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.config import (
    get_artifact_retention_empty_shard_removal_budget,
    get_artifact_retention_trash_grace_days,
)
from sase.core.agent_artifact_index_lifecycle_common import (
    default_agent_artifact_projects_root,
)
from sase.core.agent_artifact_index_lifecycle_mutations import (
    delete_agent_artifact_index_artifacts,
    upsert_agent_artifact_index_artifacts,
)
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_artifact_run_retention import (
    protection_reasons_for_dirs,
    recent_month_names,
)
from sase.core.agent_artifact_run_retention_models import (
    AceRunProtectionSnapshot,
    AceRunRetentionPlan,
)
from sase.core.agent_artifact_shards import (
    iter_startup_ace_run_shard_watch_paths,
)
from sase.core.continuation_retention import collect_one_continuation_run
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding


AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION = 2


def _run_trash_root() -> Path:
    """Return the ACE-run trash root, outside every scanned projects tree."""

    return sase_home() / "trash" / "ace-run"


def _require_run_trash_wire_schema() -> None:
    binding = require_rust_binding("agent_artifact_run_trash_wire_schema_version")
    actual = int(binding())
    if actual != AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs agent artifact run trash wire schema "
            f"{actual} is incompatible with Python schema "
            f"{AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION}"
        )


def _call_binding(name: str, request: Mapping[str, Any] | None = None) -> Any:
    _require_run_trash_wire_schema()
    binding = require_rust_binding(name)
    payload = binding(dict(request)) if request is not None else binding()
    assert isinstance(payload, dict)
    return payload


def _new_batch_id(now: datetime) -> str:
    slug = now.strftime("%Y%m%d%H%M%S")
    return f"run-{slug}-{secrets.token_hex(4)}"


def _restorable_until(created_at: datetime, grace_days: int) -> str:
    return (created_at + timedelta(days=grace_days)).isoformat()


def _kept_by_reason(items: Sequence[AceRunTrashItemOutcome]) -> dict[str, int]:
    rollup: dict[str, int] = {}
    for item in items:
        if item.outcome != "kept":
            continue
        for reason in item.reasons or ("unspecified",):
            rollup[reason] = rollup.get(reason, 0) + 1
    return dict(sorted(rollup.items()))


def _normalized_dir(value: Path | str) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


@dataclass(frozen=True)
class AceRunTrashItemOutcome:
    """One quarantined, kept, or skipped run directory."""

    artifact_dir: str
    project: str
    timestamp: str
    outcome: str
    reasons: tuple[str, ...] = ()
    detail: str | None = None
    bytes: int = 0
    original_path: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact_dir": self.artifact_dir,
            "project": self.project,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "detail": self.detail,
            "bytes": self.bytes,
            "original_path": self.original_path,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> AceRunTrashItemOutcome:
        original_path = str(payload.get("original_path") or "")
        artifact_dir = str(payload.get("artifact_dir") or original_path or "")
        return cls(
            artifact_dir=artifact_dir,
            project=str(payload.get("project") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            outcome=str(payload.get("outcome") or ""),
            reasons=tuple(str(reason) for reason in payload.get("reasons") or ()),
            detail=(None if payload.get("detail") is None else str(payload["detail"])),
            bytes=int(payload.get("bytes") or 0),
            original_path=original_path,
        )


@dataclass(frozen=True)
class AceRunTrashBatch:
    """One journaled trash batch."""

    id: str
    created_at: str
    status: str
    run_count: int
    bytes: int
    projects: tuple[str, ...]
    orphan_items: tuple[AceRunTrashItemOutcome, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "status": self.status,
            "run_count": self.run_count,
            "bytes": self.bytes,
            "projects": list(self.projects),
            "orphan_items": [item.to_json_dict() for item in self.orphan_items],
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> AceRunTrashBatch:
        return cls(
            id=str(payload.get("id") or ""),
            created_at=str(payload.get("created_at") or ""),
            status=str(payload.get("status") or ""),
            run_count=int(payload.get("run_count") or 0),
            bytes=int(payload.get("bytes") or 0),
            projects=tuple(str(p) for p in payload.get("projects") or ()),
            orphan_items=tuple(
                AceRunTrashItemOutcome.from_json_dict(item)
                for item in payload.get("orphan_items") or ()
            ),
        )


@dataclass(frozen=True)
class AceRunTrashQuarantineResult:
    """Outcome of quarantining reviewed runs into restorable trash."""

    batch_id: str
    status: str
    requested: int
    quarantined: int
    kept: int
    not_reviewed: int
    errors: int
    bytes_quarantined: int
    blocked_reason: str | None
    items: tuple[AceRunTrashItemOutcome, ...]
    kept_by_reason: dict[str, int]
    removed_empty_shards: int
    journal_path: str
    deindexed: int
    index_errors: tuple[str, ...]
    restorable_until: str
    created_at: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "status": self.status,
            "requested": self.requested,
            "quarantined": self.quarantined,
            "kept": self.kept,
            "not_reviewed": self.not_reviewed,
            "errors": self.errors,
            "bytes_quarantined": self.bytes_quarantined,
            "blocked_reason": self.blocked_reason,
            "items": [item.to_json_dict() for item in self.items],
            "kept_by_reason": dict(self.kept_by_reason),
            "removed_empty_shards": self.removed_empty_shards,
            "journal_path": self.journal_path,
            "deindexed": self.deindexed,
            "index_errors": list(self.index_errors),
            "restorable_until": self.restorable_until,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AceRunTrashListResult:
    """Newest-first listing of journaled trash batches."""

    batches: tuple[AceRunTrashBatch, ...]
    unreadable_journal_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "batches": [batch.to_json_dict() for batch in self.batches],
            "unreadable_journal_count": self.unreadable_journal_count,
        }


@dataclass(frozen=True)
class AceRunTrashRestoreResult:
    """Outcome of restoring a trash batch back into the projects tree."""

    batch_id: str
    status: str
    restored: int
    conflicts: int
    errors: int
    restored_dirs: tuple[str, ...]
    items: tuple[AceRunTrashItemOutcome, ...]
    blocked_reason: str | None
    reindexed: int
    index_errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "status": self.status,
            "restored": self.restored,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "restored_dirs": list(self.restored_dirs),
            "items": [item.to_json_dict() for item in self.items],
            "blocked_reason": self.blocked_reason,
            "reindexed": self.reindexed,
            "index_errors": list(self.index_errors),
        }


@dataclass(frozen=True)
class AceRunTrashPurgeResult:
    """Outcome of permanently purging expired trash batches."""

    status: str
    purged: int
    kept: int
    restored: int
    errors: int
    freed_bytes: int
    restored_dirs: tuple[str, ...]
    purged_batches: tuple[str, ...]
    items: tuple[AceRunTrashItemOutcome, ...]
    blocked_reason: str | None
    reindexed: int
    index_errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "status": self.status,
            "purged": self.purged,
            "kept": self.kept,
            "restored": self.restored,
            "errors": self.errors,
            "freed_bytes": self.freed_bytes,
            "restored_dirs": list(self.restored_dirs),
            "purged_batches": list(self.purged_batches),
            "items": [item.to_json_dict() for item in self.items],
            "blocked_reason": self.blocked_reason,
            "reindexed": self.reindexed,
            "index_errors": list(self.index_errors),
        }


@dataclass(frozen=True)
class ReviewedRunSet:
    """Reviewed run dirs loaded from a snapshot, keyed by canonical dir."""

    fingerprint: str
    dirs: frozenset[str] = field(default_factory=frozenset)


def quarantine_ace_runs(
    plan: AceRunRetentionPlan,
    protections: AceRunProtectionSnapshot,
    *,
    reviewed: ReviewedRunSet | None = None,
    trash_root: Path | str | None = None,
    index_path: Path | str | None = None,
    now: datetime | None = None,
) -> AceRunTrashQuarantineResult:
    """Quarantine fresh-selected runs into restorable trash.

    When *reviewed* is given, only the intersection of the fresh plan and
    the reviewed set moves: reviewed items that are no longer eligible are
    reported as kept with their fresh reasons, and eligible but unreviewed
    items are reported as ``not_reviewed`` and left untouched.
    """

    moment = now or datetime.now(UTC)
    root = _run_trash_root() if trash_root is None else Path(trash_root).expanduser()
    projects_root = plan.policy.normalized_projects_root()
    created_at = moment.isoformat()
    batch_id = _new_batch_id(moment)
    grace_days = get_artifact_retention_trash_grace_days()
    restorable_until = _restorable_until(moment, grace_days)

    selected_by_dir = {
        _normalized_dir(item.artifact_dir): item for item in plan.selected
    }
    protected_by_dir = {
        _normalized_dir(item.artifact_dir): item for item in plan.protected
    }
    reviewed_dirs = None if reviewed is None else set(reviewed.dirs)

    eligible_dirs = sorted(selected_by_dir)
    if reviewed_dirs is not None:
        eligible_dirs = [d for d in eligible_dirs if d in reviewed_dirs]
    not_reviewed_items = tuple(
        AceRunTrashItemOutcome(
            artifact_dir=item.artifact_dir,
            project=item.project,
            timestamp=item.timestamp,
            outcome="not_reviewed",
            reasons=("not_reviewed",),
            bytes=item.size_bytes,
        )
        for path, item in sorted(selected_by_dir.items())
        if reviewed_dirs is not None and path not in reviewed_dirs
    )
    stale_review_items: list[AceRunTrashItemOutcome] = []
    if reviewed_dirs is not None:
        for path in sorted(reviewed_dirs - set(selected_by_dir)):
            protected = protected_by_dir.get(path)
            if protected is not None:
                reasons = tuple(protected.reasons) or ("protected",)
                stale_review_items.append(
                    AceRunTrashItemOutcome(
                        artifact_dir=protected.artifact_dir,
                        project=protected.project,
                        timestamp=protected.timestamp,
                        outcome="kept",
                        reasons=tuple(f"protected:{r}" for r in reasons),
                    )
                )
            else:
                stale_review_items.append(
                    AceRunTrashItemOutcome(
                        artifact_dir=path,
                        project="",
                        timestamp="",
                        outcome="kept",
                        reasons=("not_selected",),
                    )
                )

    sources_unavailable = sorted(
        set(plan.sources_unavailable) | set(protections.sources_unavailable)
    )
    if sources_unavailable or not eligible_dirs:
        # Nothing reaches the owner: unavailable protections block with zero
        # filesystem effects, and an empty selection needs no batch.
        blocked = "protection_unavailable" if sources_unavailable else None
        items = tuple(stale_review_items) + not_reviewed_items
        return AceRunTrashQuarantineResult(
            batch_id=batch_id,
            status="blocked" if blocked else "complete",
            requested=len(selected_by_dir),
            quarantined=0,
            kept=len(stale_review_items),
            not_reviewed=len(not_reviewed_items),
            errors=0,
            bytes_quarantined=0,
            blocked_reason=blocked,
            items=items,
            kept_by_reason=_kept_by_reason(items),
            removed_empty_shards=0,
            journal_path="",
            deindexed=0,
            index_errors=(),
            restorable_until=restorable_until,
            created_at=created_at,
        )

    reasons_by_dir = protection_reasons_for_dirs(
        eligible_dirs, protections, projects_root=projects_root
    )
    wire_items = [
        {
            "artifact_dir": selected_by_dir[path].artifact_dir,
            "project": selected_by_dir[path].project,
            "timestamp": selected_by_dir[path].timestamp,
            "protected_reasons": reasons_by_dir.get(path, ["scan_unavailable"]),
        }
        for path in eligible_dirs
    ]
    eligible_projects = sorted(
        {selected_by_dir[path].project for path in eligible_dirs}
    )
    shard_roots: list[str] = []
    shard_watched: list[str] = []
    for project in eligible_projects:
        workflow_dir = projects_root / project / "artifacts" / ACE_RUN_WORKFLOW_DIR
        if workflow_dir.is_dir():
            shard_roots.append(str(workflow_dir))
            shard_watched.extend(
                str(path)
                for path in iter_startup_ace_run_shard_watch_paths(
                    workflow_dir, now=plan.policy.now
                )
            )
    request = {
        "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
        "projects_root": str(projects_root),
        "sources_unavailable": sources_unavailable,
        "protected_dirs": sorted(protections.protected_dirs),
        "protected_timestamps": sorted(protections.protected_timestamps),
        "recent_months": list(
            recent_month_names(plan.policy.now, plan.policy.keep_recent_months)
        ),
        "current_timestamp": plan.policy.now.strftime("%Y%m%d%H%M%S"),
        "items": wire_items,
        "trash_root": str(root),
        "batch_id": batch_id,
        "created_at": created_at,
        "empty_shard_roots": shard_roots,
        "empty_shard_watched_paths": sorted(set(shard_watched)),
        "empty_shard_removal_budget": (
            get_artifact_retention_empty_shard_removal_budget()
        ),
    }
    raw = _call_binding("quarantine_agent_artifact_runs", request)
    owner_items = tuple(
        AceRunTrashItemOutcome.from_json_dict(item) for item in raw.get("items") or ()
    )
    moved_dirs = [
        item.artifact_dir for item in owner_items if item.outcome == "quarantined"
    ]
    deindexed = 0
    index_errors: list[str] = []
    if moved_dirs and raw.get("blocked_reason") is None:
        try:
            deindexed = delete_agent_artifact_index_artifacts(
                moved_dirs, index_path=index_path
            )
        except Exception as exc:  # noqa: BLE001 - moves stand; report the failure.
            index_errors.append(f"deindex after quarantine failed: {exc}")
    items = owner_items + tuple(stale_review_items) + not_reviewed_items
    return AceRunTrashQuarantineResult(
        batch_id=str(raw.get("batch_id") or batch_id),
        status=str(raw.get("status") or "blocked"),
        requested=int(raw.get("requested") or len(wire_items)),
        quarantined=int(raw.get("quarantined") or 0),
        kept=int(raw.get("kept") or 0) + len(stale_review_items),
        not_reviewed=len(not_reviewed_items),
        errors=int(raw.get("errors") or 0),
        bytes_quarantined=int(raw.get("bytes_quarantined") or 0),
        blocked_reason=(
            None if raw.get("blocked_reason") is None else str(raw["blocked_reason"])
        ),
        items=items,
        kept_by_reason=_kept_by_reason(items),
        removed_empty_shards=int(raw.get("removed_empty_shards") or 0),
        journal_path=str(raw.get("journal_path") or ""),
        deindexed=deindexed,
        index_errors=tuple(index_errors),
        restorable_until=restorable_until,
        created_at=created_at,
    )


def list_ace_run_trash(
    trash_root: Path | str | None = None,
) -> AceRunTrashListResult:
    """List journaled ACE-run trash batches, newest first."""

    root = _run_trash_root() if trash_root is None else Path(trash_root).expanduser()
    if not root.is_dir():
        return AceRunTrashListResult(batches=(), unreadable_journal_count=0)
    _require_run_trash_wire_schema()
    binding = require_rust_binding("list_agent_artifact_run_trash")
    payload = binding(str(root))
    assert isinstance(payload, dict)
    return AceRunTrashListResult(
        batches=tuple(
            AceRunTrashBatch.from_json_dict(batch)
            for batch in payload.get("batches") or ()
        ),
        unreadable_journal_count=int(payload.get("unreadable_journal_count") or 0),
    )


def restore_ace_run_trash(
    batch_id: str,
    *,
    items: Sequence[str] | None = None,
    projects_root: Path | str | None = None,
    trash_root: Path | str | None = None,
    index_path: Path | str | None = None,
) -> AceRunTrashRestoreResult:
    """Restore a trash batch (or selected original paths) and re-index."""

    root = _run_trash_root() if trash_root is None else Path(trash_root).expanduser()
    resolved_projects_root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else default_agent_artifact_projects_root()
    )
    request: dict[str, Any] = {
        "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
        "trash_root": str(root),
        "projects_root": str(resolved_projects_root),
        "batch_id": batch_id,
        "items": None if items is None else [str(item) for item in items],
    }
    raw = _call_binding("restore_agent_artifact_run_trash", request)
    restored_dirs = tuple(str(path) for path in raw.get("restored_dirs") or ())
    reindexed = 0
    index_errors: list[str] = []
    if restored_dirs and raw.get("blocked_reason") is None:
        try:
            reindexed = upsert_agent_artifact_index_artifacts(
                restored_dirs, index_path=index_path
            )
        except Exception as exc:  # noqa: BLE001 - restores stand; report it.
            index_errors.append(f"reindex after restore failed: {exc}")
    return AceRunTrashRestoreResult(
        batch_id=str(raw.get("batch_id") or batch_id),
        status=str(raw.get("status") or "blocked"),
        restored=int(raw.get("restored") or 0),
        conflicts=int(raw.get("conflicts") or 0),
        errors=int(raw.get("errors") or 0),
        restored_dirs=restored_dirs,
        items=tuple(
            AceRunTrashItemOutcome.from_json_dict(item)
            for item in raw.get("items") or ()
        ),
        blocked_reason=(
            None if raw.get("blocked_reason") is None else str(raw["blocked_reason"])
        ),
        reindexed=reindexed,
        index_errors=tuple(index_errors),
    )


def purge_ace_run_trash(
    protections: AceRunProtectionSnapshot,
    *,
    purge_all: bool = False,
    projects_root: Path | str | None = None,
    trash_root: Path | str | None = None,
    index_path: Path | str | None = None,
    now: datetime | None = None,
) -> AceRunTrashPurgeResult:
    """Purge expired trash batches; restores runs that gained a reference.

    The cutoff is now minus ``artifacts.retention.trash_grace_days``.
    Unavailable protections block only the run part with nothing deleted.
    """

    moment = now or datetime.now(UTC)
    root = _run_trash_root() if trash_root is None else Path(trash_root).expanduser()
    resolved_projects_root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else default_agent_artifact_projects_root()
    )
    sources_unavailable = sorted(protections.sources_unavailable)
    if sources_unavailable:
        return AceRunTrashPurgeResult(
            status="blocked",
            purged=0,
            kept=0,
            restored=0,
            errors=0,
            freed_bytes=0,
            restored_dirs=(),
            purged_batches=(),
            items=(),
            blocked_reason="protection_unavailable",
            reindexed=0,
            index_errors=(),
        )
    cutoff = (
        moment - timedelta(days=get_artifact_retention_trash_grace_days())
    ).isoformat()
    request: dict[str, Any] = {
        "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
        "trash_root": str(root),
        "projects_root": str(resolved_projects_root),
        "before": None if purge_all else cutoff,
        "purge_all": purge_all,
        "sources_unavailable": sources_unavailable,
        "protected_dirs": sorted(protections.protected_dirs),
        "protected_timestamps": sorted(protections.protected_timestamps),
        "protected_agent_names": sorted(protections.protected_agent_names),
        "non_closed_bead_ids_by_project": {
            project: sorted(ids)
            for project, ids in sorted(
                protections.non_closed_bead_ids_by_project.items()
            )
        },
        "continuation_runs": _continuation_runs_for_purge(
            projects_root=resolved_projects_root,
            trash_root=root,
        ),
    }
    raw = _call_binding("purge_agent_artifact_run_trash", request)
    restored_dirs = tuple(str(path) for path in raw.get("restored_dirs") or ())
    reindexed = 0
    index_errors: list[str] = []
    if restored_dirs and raw.get("blocked_reason") is None:
        try:
            reindexed = upsert_agent_artifact_index_artifacts(
                restored_dirs, index_path=index_path
            )
        except Exception as exc:  # noqa: BLE001 - purge stands; report it.
            index_errors.append(f"reindex after purge failed: {exc}")
    return AceRunTrashPurgeResult(
        status=str(raw.get("status") or "blocked"),
        purged=int(raw.get("purged") or 0),
        kept=int(raw.get("kept") or 0),
        restored=int(raw.get("restored") or 0),
        errors=int(raw.get("errors") or 0),
        freed_bytes=int(raw.get("freed_bytes") or 0),
        restored_dirs=restored_dirs,
        purged_batches=tuple(str(b) for b in raw.get("purged_batches") or ()),
        items=tuple(
            AceRunTrashItemOutcome.from_json_dict(item)
            for item in raw.get("items") or ()
        ),
        blocked_reason=(
            None if raw.get("blocked_reason") is None else str(raw["blocked_reason"])
        ),
        reindexed=reindexed,
        index_errors=tuple(index_errors),
    )


def _is_real_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


def _iter_timestamp_run_dirs(workflow_root: Path) -> list[Path]:
    found: list[Path] = []
    if not _is_real_dir(workflow_root):
        return found
    try:
        month_entries = sorted(workflow_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return found
    for month in month_entries:
        if not _is_real_dir(month) or len(month.name) != 6 or not month.name.isdigit():
            continue
        try:
            day_entries = sorted(month.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for day in day_entries:
            if not _is_real_dir(day) or len(day.name) != 2 or not day.name.isdigit():
                continue
            try:
                run_entries = sorted(day.iterdir(), key=lambda path: path.name)
            except OSError:
                continue
            for stamp in run_entries:
                if (
                    not _is_real_dir(stamp)
                    or len(stamp.name) != 14
                    or not stamp.name.isdigit()
                    or not stamp.name.startswith(month.name)
                    or stamp.name[6:8] != day.name
                ):
                    continue
                found.append(stamp)
    return found


def _iter_live_ace_run_dirs(projects_root: Path) -> list[Path]:
    found: list[Path] = []
    if not _is_real_dir(projects_root):
        return found
    try:
        projects = sorted(projects_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return found
    for project in projects:
        if not _is_real_dir(project):
            continue
        found.extend(
            _iter_timestamp_run_dirs(project / "artifacts" / ACE_RUN_WORKFLOW_DIR)
        )
    return found


def _iter_trash_run_identities(
    trash_root: Path, projects_root: Path
) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    if not _is_real_dir(trash_root):
        return pairs
    try:
        batches = sorted(trash_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return pairs
    for batch in batches:
        runs_root = batch / "runs"
        if not _is_real_dir(batch) or not _is_real_dir(runs_root):
            continue
        try:
            projects = sorted(runs_root.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for project_dir in projects:
            if not _is_real_dir(project_dir):
                continue
            for physical in _iter_timestamp_run_dirs(project_dir):
                logical = (
                    projects_root
                    / project_dir.name
                    / "artifacts"
                    / ACE_RUN_WORKFLOW_DIR
                    / physical.parent.parent.name
                    / physical.parent.name
                    / physical.name
                )
                pairs.append((physical, logical))
    return pairs


def _continuation_runs_for_purge(
    *,
    projects_root: Path,
    trash_root: Path,
) -> list[dict[str, Any]]:
    """Collect continuation observations; live identity wins over trash bytes."""

    observations: dict[str, dict[str, Any]] = {}
    for live_dir in _iter_live_ace_run_dirs(projects_root):
        key = _normalized_dir(live_dir)
        observations[key] = collect_one_continuation_run(
            live_dir,
            artifact_dir=key,
            projects_root=projects_root,
        )
    for physical, logical in _iter_trash_run_identities(trash_root, projects_root):
        key = _normalized_dir(logical)
        if key in observations:
            continue
        observations[key] = collect_one_continuation_run(
            physical,
            artifact_dir=key,
            projects_root=projects_root,
        )
    return list(observations.values())


__all__ = [
    "AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION",
    "AceRunTrashBatch",
    "AceRunTrashItemOutcome",
    "AceRunTrashListResult",
    "AceRunTrashPurgeResult",
    "AceRunTrashQuarantineResult",
    "AceRunTrashRestoreResult",
    "ReviewedRunSet",
    "list_ace_run_trash",
    "purge_ace_run_trash",
    "quarantine_ace_runs",
    "restore_ace_run_trash",
]
