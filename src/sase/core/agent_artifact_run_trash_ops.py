"""List, restore, and purge journaled ACE-run trash batches.

Split out of :mod:`sase.core.agent_artifact_run_trash` to keep each
module under the 500-line cap. Quarantine lives in
:mod:`sase.core.agent_artifact_run_trash_quarantine`. The public import
path remains :mod:`sase.core.agent_artifact_run_trash`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_trash_grace_days
from sase.core._agent_artifact_run_trash_shared import (
    call_run_trash_binding,
    normalized_dir,
    require_run_trash_wire_schema,
    run_trash_root,
)
from sase.core.agent_artifact_index_lifecycle_common import (
    default_agent_artifact_projects_root,
)
from sase.core.agent_artifact_index_lifecycle_mutations import (
    upsert_agent_artifact_index_artifacts,
)
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_artifact_run_retention_models import AceRunProtectionSnapshot
from sase.core.agent_artifact_run_trash_models import (
    AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
    AceRunTrashBatch,
    AceRunTrashItemOutcome,
    AceRunTrashListResult,
    AceRunTrashPurgeResult,
    AceRunTrashRestoreResult,
)
from sase.core.continuation_retention import collect_one_continuation_run
from sase.core.rust import require_rust_binding


def list_ace_run_trash(
    trash_root: Path | str | None = None,
) -> AceRunTrashListResult:
    """List journaled ACE-run trash batches, newest first."""

    root = run_trash_root() if trash_root is None else Path(trash_root).expanduser()
    if not root.is_dir():
        return AceRunTrashListResult(batches=(), unreadable_journal_count=0)
    require_run_trash_wire_schema()
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

    root = run_trash_root() if trash_root is None else Path(trash_root).expanduser()
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
    raw = call_run_trash_binding("restore_agent_artifact_run_trash", request)
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
    root = run_trash_root() if trash_root is None else Path(trash_root).expanduser()
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
    raw = call_run_trash_binding("purge_agent_artifact_run_trash", request)
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
        key = normalized_dir(live_dir)
        observations[key] = collect_one_continuation_run(
            live_dir,
            artifact_dir=key,
            projects_root=projects_root,
        )
    for physical, logical in _iter_trash_run_identities(trash_root, projects_root):
        key = normalized_dir(logical)
        if key in observations:
            continue
        observations[key] = collect_one_continuation_run(
            physical,
            artifact_dir=key,
            projects_root=projects_root,
        )
    return list(observations.values())


__all__ = [
    "list_ace_run_trash",
    "purge_ace_run_trash",
    "restore_ace_run_trash",
]
