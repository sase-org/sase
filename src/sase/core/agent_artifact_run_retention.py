"""Retention planning for per-project ACE-run artifact directories."""

from __future__ import annotations

import os
import shutil
import stat
from datetime import datetime
from pathlib import Path

from sase.core.agent_artifact_index_lifecycle_mutations import (
    delete_agent_artifact_index_artifacts,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    iter_agent_artifact_dirs,
    parse_agent_artifact_path,
)
from sase.core.agent_artifact_run_protection import (
    collect_ace_run_retention_protections,
)
from sase.core.agent_artifact_run_retention_models import (
    ACE_RUN_RETENTION_SCHEMA_VERSION,
    DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS,
    AceRunProtectionSnapshot,
    AceRunRetentionApplyResult,
    AceRunRetentionCounts,
    AceRunRetentionItem,
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    EmptyAceRunShard,
    ProtectedAceRunItem,
)
from sase.core.agent_artifact_shards import (
    is_ace_run_day_shard_name,
    iter_ace_run_month_dirs,
    iter_startup_ace_run_shard_watch_paths,
)
from sase.core.agent_scan_facade import scan_agent_artifact_dirs
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import is_valid_sase_project_name


_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=(ACE_RUN_WORKFLOW_DIR,),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=True,
    include_workflow_state=True,
    include_waiting=True,
)


def plan_ace_run_retention(
    policy: AceRunRetentionPolicy,
    protections: AceRunProtectionSnapshot | None = None,
) -> AceRunRetentionPlan:
    """Return what ACE-run retention would reclaim without deleting anything."""

    protection_snapshot = protections or collect_ace_run_retention_protections(
        projects_root=policy.projects_root
    )
    projects_root = policy.normalized_projects_root()
    project_names = _project_names(projects_root, policy.project)
    recent_months = _recent_month_names(policy.now, policy.keep_recent_months)
    current_timestamp = policy.now.strftime("%Y%m%d%H%M%S")

    selected_all: list[AceRunRetentionItem] = []
    protected: list[ProtectedAceRunItem] = []
    unavailable = set(protection_snapshot.sources_unavailable)

    for project in project_names:
        artifact_dirs = tuple(
            iter_agent_artifact_dirs(
                project,
                ACE_RUN_WORKFLOW_DIR,
                projects_root=projects_root,
                newest_first=False,
            )
        )
        records, scan_error = _scan_records(projects_root, artifact_dirs)
        if scan_error is not None:
            unavailable.add(scan_error)
        for artifact_dir in artifact_dirs:
            info = parse_agent_artifact_path(artifact_dir, projects_root=projects_root)
            if info is None:
                continue
            record = records.get(_normalized_path(artifact_dir))
            reasons = _protection_reasons(
                project=project,
                timestamp=info.timestamp,
                artifact_dir=artifact_dir,
                record=record,
                protections=protection_snapshot,
                recent_months=recent_months,
                current_timestamp=current_timestamp,
                scan_unavailable=scan_error is not None,
            )
            if reasons:
                protected.append(
                    ProtectedAceRunItem(
                        project=project,
                        timestamp=info.timestamp,
                        artifact_dir=str(artifact_dir),
                        reasons=tuple(reasons),
                    )
                )
                continue
            selected_all.append(
                AceRunRetentionItem(
                    project=project,
                    timestamp=info.timestamp,
                    artifact_dir=str(artifact_dir),
                    size_bytes=_tree_size(artifact_dir),
                    reason=f"older_than_recent_{policy.keep_recent_months}_months",
                )
            )

    selected_all.sort(
        key=lambda item: (item.timestamp, item.project, item.artifact_dir)
    )
    limit = policy.limit
    selected = tuple(selected_all if limit is None else selected_all[: max(limit, 0)])
    empty_shards = _empty_out_of_range_shards(
        project_names,
        projects_root=projects_root,
        now=policy.now,
    )
    counts = AceRunRetentionCounts(
        candidates=len(selected_all) + len(protected),
        selected=len(selected),
        protected=len(protected),
        empty_out_of_range_shards=len(empty_shards),
        truncated=max(0, len(selected_all) - len(selected)),
    )
    return AceRunRetentionPlan(
        policy=policy,
        protections=protection_snapshot,
        selected=selected,
        protected=tuple(
            sorted(protected, key=lambda item: (item.timestamp, item.project))
        ),
        empty_out_of_range_shards=tuple(empty_shards),
        counts=counts,
        reclaimable_bytes=sum(item.size_bytes for item in selected),
        sources_unavailable=tuple(sorted(unavailable)),
    )


def apply_ace_run_retention(
    plan: AceRunRetentionPlan,
    *,
    index_path: Path | str | None = None,
) -> AceRunRetentionApplyResult:
    """Delete selected run directories and empty out-of-range shards."""

    removed_dirs: list[Path] = []
    skipped: list[str] = []
    errors: list[str] = []
    bytes_reclaimed = 0

    for item in plan.selected:
        path = Path(item.artifact_dir).expanduser()
        if _has_active_marker(path):
            skipped.append(f"{path}: active marker appeared before apply")
            continue
        size_bytes = item.size_bytes or _tree_size(path)
        removed, message = _remove_run_dir(path)
        if not removed:
            skipped.append(message)
            continue
        removed_dirs.append(path)
        bytes_reclaimed += size_bytes

    deindexed = (
        delete_agent_artifact_index_artifacts(removed_dirs, index_path=index_path)
        if removed_dirs
        else 0
    )
    projects_root = plan.policy.normalized_projects_root()
    empty_shards = _empty_out_of_range_shards(
        _project_names(projects_root, plan.policy.project),
        projects_root=projects_root,
        now=plan.policy.now,
    )
    removed_empty_shards = 0
    for shard in empty_shards:
        path = Path(shard.path).expanduser()
        try:
            path.rmdir()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        removed_empty_shards += 1

    return AceRunRetentionApplyResult(
        removed_runs=len(removed_dirs),
        removed_empty_shards=removed_empty_shards,
        bytes_reclaimed=bytes_reclaimed,
        deindexed=deindexed,
        skipped=tuple(skipped),
        errors=tuple(errors),
    )


def _project_names(projects_root: Path, project: str | None) -> tuple[str, ...]:
    if project is not None:
        return (project,)
    try:
        children = tuple(projects_root.iterdir())
    except OSError:
        return ()
    return tuple(
        sorted(
            child.name
            for child in children
            if child.is_dir() and is_valid_sase_project_name(child.name)
        )
    )


def _scan_records(
    projects_root: Path,
    artifact_dirs: tuple[Path, ...],
) -> tuple[dict[str, AgentArtifactRecordWire], str | None]:
    if not artifact_dirs:
        return {}, None
    try:
        snapshot = scan_agent_artifact_dirs(projects_root, artifact_dirs, _SCAN_OPTIONS)
    except Exception as exc:  # noqa: BLE001 - apply blocks on this coverage gap.
        return {}, f"agent artifact scan: {exc}"
    return (
        {_normalized_path(record.artifact_dir): record for record in snapshot.records},
        None,
    )


def _protection_reasons(
    *,
    project: str,
    timestamp: str,
    artifact_dir: Path,
    record: AgentArtifactRecordWire | None,
    protections: AceRunProtectionSnapshot,
    recent_months: frozenset[str],
    current_timestamp: str,
    scan_unavailable: bool,
) -> list[str]:
    reasons: list[str] = []
    normalized_dir = _normalized_path(artifact_dir)
    if normalized_dir in protections.protected_dirs:
        reasons.append("referenced_dir")
    if timestamp in protections.protected_timestamps:
        reasons.append("referenced_timestamp")
    if _normalized_path(os.getenv("SASE_ARTIFACTS_DIR") or "") == normalized_dir:
        reasons.append("current_agent")
    if timestamp[:6] in recent_months:
        reasons.append("recent_month")
    if timestamp > current_timestamp:
        reasons.append("future_timestamp")
    if _is_symlink(artifact_dir):
        reasons.append("symlink")
    if scan_unavailable:
        reasons.append("scan_unavailable")
    if record is None:
        reasons.append("missing_scan_record")
        return _dedupe(reasons)
    if not record.has_done_marker:
        reasons.append("not_terminal")
    if record.running is not None:
        reasons.append("running")
    if record.waiting is not None:
        reasons.append("waiting")
    if record.pending_question is not None:
        reasons.append("pending_question")
    if _record_agent_names(record) & protections.protected_agent_names:
        reasons.append("referenced_agent")
    live_beads = protections.non_closed_bead_ids_by_project.get(project, frozenset())
    if _record_bead_ids(record) & live_beads:
        reasons.append("non_closed_bead")
    return _dedupe(reasons)


def _record_agent_names(record: AgentArtifactRecordWire) -> frozenset[str]:
    names: set[str] = set()
    if record.agent_meta is not None:
        names.update(
            value
            for value in (
                record.agent_meta.name,
                record.agent_meta.artifact_agent_id,
            )
            if value
        )
    if record.done is not None and record.done.name:
        names.add(record.done.name)
    return frozenset(names)


def _record_bead_ids(record: AgentArtifactRecordWire) -> frozenset[str]:
    if record.agent_meta is None:
        return frozenset()
    return frozenset(
        value
        for value in (
            record.agent_meta.bead_id,
            record.agent_meta.phase_bead_id,
            record.agent_meta.epic_bead_id,
        )
        if value
    )


def _empty_out_of_range_shards(
    project_names: tuple[str, ...],
    *,
    projects_root: Path,
    now: datetime,
) -> list[EmptyAceRunShard]:
    shards: list[EmptyAceRunShard] = []
    seen: set[str] = set()
    for project in project_names:
        workflow_dir = projects_root / project / "artifacts" / ACE_RUN_WORKFLOW_DIR
        if not workflow_dir.is_dir():
            continue
        watched = {
            _normalized_path(path)
            for path in iter_startup_ace_run_shard_watch_paths(workflow_dir, now=now)
        }
        for month_dir in iter_ace_run_month_dirs(workflow_dir):
            if _normalized_path(month_dir) not in watched and _empty_dir_tree(
                month_dir
            ):
                _append_empty_shard(shards, seen, project, month_dir, "month")
            for day_dir in _iter_day_dirs(month_dir):
                if _normalized_path(day_dir) in watched or not _empty_dir_tree(day_dir):
                    continue
                _append_empty_shard(shards, seen, project, day_dir, "day")
    return sorted(shards, key=lambda item: (-len(Path(item.path).parts), item.path))


def _append_empty_shard(
    shards: list[EmptyAceRunShard],
    seen: set[str],
    project: str,
    path: Path,
    kind: str,
) -> None:
    key = _normalized_path(path)
    if key in seen:
        return
    seen.add(key)
    shards.append(
        EmptyAceRunShard(
            project=project,
            path=str(path),
            kind=kind,
            reason="outside_startup_shard_window",
        )
    )


def _iter_day_dirs(month_dir: Path) -> tuple[Path, ...]:
    try:
        children = tuple(month_dir.iterdir())
    except OSError:
        return ()
    return tuple(
        child
        for child in children
        if child.is_dir()
        and not child.is_symlink()
        and is_ace_run_day_shard_name(child.name)
    )


def _empty_dir_tree(path: Path) -> bool:
    try:
        children = tuple(path.iterdir())
    except OSError:
        return False
    for child in children:
        if child.is_symlink():
            return False
        if child.is_dir():
            if not _empty_dir_tree(child):
                return False
        else:
            return False
    return True


def _recent_month_names(now: datetime, keep_recent_months: int) -> frozenset[str]:
    count = max(1, keep_recent_months)
    year = now.year
    month = now.month
    names: list[str] = []
    for _ in range(count):
        names.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return frozenset(names)


def _tree_size(path: Path) -> int:
    try:
        entry_stat = path.stat(follow_symlinks=False)
    except OSError:
        return 0
    if stat.S_ISLNK(entry_stat.st_mode):
        return 0
    if stat.S_ISREG(entry_stat.st_mode):
        return int(entry_stat.st_size)
    if not stat.S_ISDIR(entry_stat.st_mode):
        return 0
    total = int(entry_stat.st_size)
    try:
        children = tuple(path.iterdir())
    except OSError:
        return total
    for child in children:
        total += _tree_size(child)
    return total


def _remove_run_dir(path: Path) -> tuple[bool, str]:
    try:
        entry_stat = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False, f"{path}: already absent"
    except OSError as exc:
        return False, f"{path}: {exc}"
    if stat.S_ISLNK(entry_stat.st_mode):
        return False, f"{path}: symlink skipped"
    if not stat.S_ISDIR(entry_stat.st_mode):
        return False, f"{path}: not a directory"
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return False, f"{path}: {exc}"
    return True, f"{path}: removed"


def _has_active_marker(path: Path) -> bool:
    if not path.is_dir() or path.is_symlink():
        return False
    if not (path / "done.json").exists():
        return True
    return any(
        (path / marker).exists()
        for marker in ("running.json", "waiting.json", "pending_question.json")
    )


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.stat(follow_symlinks=False).st_mode)
    except OSError:
        return False


def _normalized_path(path: Path | str) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve(strict=False))


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "ACE_RUN_RETENTION_SCHEMA_VERSION",
    "DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS",
    "AceRunProtectionSnapshot",
    "AceRunRetentionApplyResult",
    "AceRunRetentionCounts",
    "AceRunRetentionItem",
    "AceRunRetentionPlan",
    "AceRunRetentionPolicy",
    "EmptyAceRunShard",
    "ProtectedAceRunItem",
    "apply_ace_run_retention",
    "collect_ace_run_retention_protections",
    "plan_ace_run_retention",
]
