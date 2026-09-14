"""Retention planning for per-project ACE-run artifact directories.

Protection facts (bead liveness, continuation ancestry, artifact-index
references, scan markers) are gathered here from their own Rust-backed
sources; the final classification, the canonical-root/symlink-ancestor
safety check, revalidation immediately before each deletion, and the
bottom-up empty-shard walk all live in the ``sase_core_rs`` run-retention
owner (:mod:`sase_core::agent_artifact_run_retention`). ``apply_ace_run_
retention`` never trusts the plan's snapshot: it re-collects protections and
re-scans artifact dirs immediately before calling the owner with ``apply``.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_empty_shard_removal_budget
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
    is_agent_artifact_dir_name,
    iter_startup_ace_run_shard_watch_paths,
)
from sase.core.agent_scan_facade import scan_agent_artifact_dirs
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core import continuation_retention
from sase.core.paths import is_valid_sase_project_name
from sase.core.rust import require_rust_binding


_RUN_RETENTION_WIRE_SCHEMA_VERSION = 1

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
    if not projects_root.is_dir():
        return _empty_plan(policy, protection_snapshot)
    project_names = _project_names(projects_root, policy.project)
    size_by_dir, sources_unavailable, result = _run_owner(
        policy,
        protection_snapshot,
        projects_root=projects_root,
        project_names=project_names,
        apply=False,
    )
    return _plan_from_result(
        policy,
        protection_snapshot,
        result,
        size_by_dir=size_by_dir,
        project_names=project_names,
        projects_root=projects_root,
        extra_sources_unavailable=sources_unavailable,
    )


def apply_ace_run_retention(
    plan: AceRunRetentionPlan,
    *,
    index_path: Path | str | None = None,
) -> AceRunRetentionApplyResult:
    """Delete selected run directories and empty out-of-range shards.

    Revalidates every protection source fresh — it never trusts *plan*'s
    selection, only its policy (now, horizons, project scope, limit).
    """

    policy = plan.policy
    protection_snapshot = collect_ace_run_retention_protections(
        projects_root=policy.projects_root
    )
    projects_root = policy.normalized_projects_root()
    if not projects_root.is_dir():
        return AceRunRetentionApplyResult(
            removed_runs=0,
            removed_empty_shards=0,
            bytes_reclaimed=0,
            deindexed=0,
            skipped=(),
            errors=(),
        )
    project_names = _project_names(projects_root, policy.project)
    _, _, result = _run_owner(
        policy,
        protection_snapshot,
        projects_root=projects_root,
        project_names=project_names,
        apply=True,
    )

    blocked_reason = result.get("blocked_reason")
    if blocked_reason:
        return AceRunRetentionApplyResult(
            removed_runs=0,
            removed_empty_shards=0,
            bytes_reclaimed=0,
            deindexed=0,
            skipped=(),
            errors=(f"apply refused: {blocked_reason}",),
        )

    removed_dirs = [
        Path(item["artifact_dir"]).expanduser()
        for item in result.get("run_items") or ()
        if item.get("outcome") == "removed"
    ]
    skipped = [
        f"{item['artifact_dir']}: {_apply_run_skip_detail(item)}"
        for item in result.get("run_items") or ()
        if item.get("outcome") in {"protected", "skipped"}
    ] + [
        f"{item['path']}: {item.get('detail') or item['outcome']}"
        for item in result.get("shard_items") or ()
        if item.get("outcome") == "skipped"
    ]
    errors = [
        f"{item['artifact_dir']}: {item.get('detail') or 'unknown error'}"
        for item in result.get("run_items") or ()
        if item.get("outcome") == "error"
    ] + [
        f"{item['path']}: {item.get('detail') or 'unknown error'}"
        for item in result.get("shard_items") or ()
        if item.get("outcome") == "error"
    ]

    deindexed = (
        delete_agent_artifact_index_artifacts(removed_dirs, index_path=index_path)
        if removed_dirs
        else 0
    )
    return AceRunRetentionApplyResult(
        removed_runs=int(result.get("removed_runs") or 0),
        removed_empty_shards=int(result.get("removed_empty_shards") or 0),
        bytes_reclaimed=int(result.get("bytes_reclaimed") or 0),
        deindexed=deindexed,
        skipped=tuple(skipped),
        errors=tuple(errors),
    )


def _apply_run_skip_detail(item: dict[str, Any]) -> str:
    detail = item.get("detail")
    outcome = str(item.get("outcome") or "skipped")
    if outcome != "protected":
        return str(detail or outcome)
    reasons = [
        str(reason).replace("_", " ")
        for reason in item.get("reasons") or ()
        if str(reason)
    ]
    if reasons:
        return "protected by " + ", ".join(reasons)
    return str(detail or "protected")


def _run_owner(
    policy: AceRunRetentionPolicy,
    protections: AceRunProtectionSnapshot,
    *,
    projects_root: Path,
    project_names: tuple[str, ...],
    apply: bool,
) -> tuple[dict[str, int], list[str], dict[str, Any]]:
    """Scan candidates fresh and call the Rust run-retention owner.

    Returns the per-dir size map (for reporting), the sources this scan
    pass found unavailable, and the owner's raw result dict.
    """

    candidates, size_by_dir, scan_unavailable = _collect_candidates(
        protections,
        projects_root=projects_root,
        project_names=project_names,
    )
    empty_shard_roots, empty_shard_watched_paths = _shard_roots_and_watch_paths(
        project_names, projects_root=projects_root, now=policy.now
    )
    sources_unavailable = sorted(
        set(protections.sources_unavailable) | scan_unavailable
    )
    request = {
        "schema_version": _RUN_RETENTION_WIRE_SCHEMA_VERSION,
        "projects_root": str(projects_root),
        "recent_months": sorted(
            _recent_month_names(policy.now, policy.keep_recent_months)
        ),
        "current_timestamp": policy.now.strftime("%Y%m%d%H%M%S"),
        "limit": policy.limit,
        "apply": apply,
        "sources_unavailable": sources_unavailable,
        "candidates": candidates,
        "empty_shard_roots": empty_shard_roots,
        "empty_shard_watched_paths": empty_shard_watched_paths,
        "empty_shard_removal_budget": get_artifact_retention_empty_shard_removal_budget(),
    }
    result = _call_rust(request)
    return size_by_dir, sources_unavailable, result


def _plan_from_result(
    policy: AceRunRetentionPolicy,
    protections: AceRunProtectionSnapshot,
    result: dict[str, Any],
    *,
    size_by_dir: dict[str, int],
    project_names: tuple[str, ...],
    projects_root: Path,
    extra_sources_unavailable: Sequence[str],
) -> AceRunRetentionPlan:
    selected: list[AceRunRetentionItem] = []
    protected: list[ProtectedAceRunItem] = []
    for item in result.get("run_items") or ():
        artifact_dir = str(item.get("artifact_dir") or "")
        outcome = item.get("outcome")
        if outcome == "selected":
            size_bytes = size_by_dir.get(_normalized_path(artifact_dir), 0)
            selected.append(
                AceRunRetentionItem(
                    project=str(item.get("project") or ""),
                    timestamp=str(item.get("timestamp") or ""),
                    artifact_dir=artifact_dir,
                    size_bytes=size_bytes,
                    reason=f"older_than_recent_{policy.keep_recent_months}_months",
                )
            )
        elif outcome == "protected":
            protected.append(
                ProtectedAceRunItem(
                    project=str(item.get("project") or ""),
                    timestamp=str(item.get("timestamp") or ""),
                    artifact_dir=artifact_dir,
                    reasons=tuple(item.get("reasons") or ()),
                )
            )

    empty_shards: list[EmptyAceRunShard] = []
    shard_unavailable: set[str] = set()
    for item in result.get("shard_items") or ():
        outcome = item.get("outcome")
        path = Path(str(item.get("path") or ""))
        if outcome == "would_remove":
            empty_shards.append(
                EmptyAceRunShard(
                    project=_project_for_path(path, project_names, projects_root),
                    path=str(path),
                    kind=_shard_kind(path),
                    reason="outside_startup_shard_window",
                )
            )
        elif outcome == "error":
            shard_unavailable.add(f"empty shard scan {path}: {item.get('detail')}")

    truncated = int(result.get("truncated") or 0)
    counts = AceRunRetentionCounts(
        candidates=int(result.get("candidates") or 0),
        selected=len(selected),
        protected=len(protected),
        empty_out_of_range_shards=len(empty_shards),
        truncated=truncated,
    )
    return AceRunRetentionPlan(
        policy=policy,
        protections=protections,
        selected=tuple(selected),
        protected=tuple(
            sorted(protected, key=lambda item: (item.timestamp, item.project))
        ),
        empty_out_of_range_shards=tuple(
            sorted(
                empty_shards, key=lambda item: (-len(Path(item.path).parts), item.path)
            )
        ),
        counts=counts,
        reclaimable_bytes=sum(item.size_bytes for item in selected),
        sources_unavailable=tuple(
            sorted(set(extra_sources_unavailable) | shard_unavailable)
        ),
    )


def _empty_plan(
    policy: AceRunRetentionPolicy, protections: AceRunProtectionSnapshot
) -> AceRunRetentionPlan:
    counts = AceRunRetentionCounts(
        candidates=0, selected=0, protected=0, empty_out_of_range_shards=0, truncated=0
    )
    return AceRunRetentionPlan(
        policy=policy,
        protections=protections,
        selected=(),
        protected=(),
        empty_out_of_range_shards=(),
        counts=counts,
        reclaimable_bytes=0,
        sources_unavailable=tuple(sorted(protections.sources_unavailable)),
    )


def _call_rust(request: dict[str, Any]) -> dict[str, Any]:
    _require_run_retention_wire_schema()
    binding = require_rust_binding("apply_agent_artifact_run_retention")
    payload = binding(request)
    assert isinstance(payload, dict)
    return payload


def _require_run_retention_wire_schema() -> None:
    binding = require_rust_binding("agent_artifact_run_retention_wire_schema_version")
    actual = int(binding())
    if actual != _RUN_RETENTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs agent artifact run retention wire schema "
            f"{actual} is incompatible with Python schema "
            f"{_RUN_RETENTION_WIRE_SCHEMA_VERSION}"
        )


def _collect_candidates(
    protections: AceRunProtectionSnapshot,
    *,
    projects_root: Path,
    project_names: tuple[str, ...],
) -> tuple[list[dict[str, Any]], dict[str, int], set[str]]:
    """Scan artifact dirs into Rust-bound candidates, their sizes, and any
    protection sources this scan pass itself found unavailable."""

    unavailable: set[str] = set()
    project_dirs = {
        project: tuple(
            iter_agent_artifact_dirs(
                project,
                ACE_RUN_WORKFLOW_DIR,
                projects_root=projects_root,
                newest_first=False,
            )
        )
        for project in project_names
    }
    all_dirs = tuple(
        artifact_dir
        for artifact_dirs in project_dirs.values()
        for artifact_dir in artifact_dirs
    )
    continuation_reasons: dict[str, tuple[str, ...]] = {}
    continuation_unavailable = False
    try:
        continuation_plan = continuation_retention.plan_continuation_run_retention(
            all_dirs, projects_root=projects_root
        )
    except ValueError as exc:
        unavailable.add(f"continuation retention: {exc}")
        continuation_unavailable = True
    else:
        continuation_reasons = continuation_retention.continuation_reasons_by_dir(
            continuation_plan
        )
        unavailable.update(
            continuation_retention.continuation_unavailable_sources(continuation_plan)
        )

    candidates: list[dict[str, Any]] = []
    size_by_dir: dict[str, int] = {}
    for project in project_names:
        artifact_dirs = project_dirs[project]
        records, scan_error = _scan_records(projects_root, artifact_dirs)
        if scan_error is not None:
            unavailable.add(scan_error)
        for artifact_dir in artifact_dirs:
            info = parse_agent_artifact_path(artifact_dir, projects_root=projects_root)
            if info is None:
                continue
            normalized_dir = _normalized_path(artifact_dir)
            record = records.get(normalized_dir)
            reasons = _protection_reasons(
                project=project,
                timestamp=info.timestamp,
                artifact_dir=artifact_dir,
                record=record,
                protections=protections,
                scan_unavailable=scan_error is not None,
                continuation_unavailable=continuation_unavailable,
                continuation_reasons=continuation_reasons.get(normalized_dir, ()),
            )
            size_by_dir[normalized_dir] = _tree_size(artifact_dir)
            candidates.append(
                {
                    "artifact_dir": str(artifact_dir),
                    "project": project,
                    "timestamp": info.timestamp,
                    "protected_reasons": reasons,
                }
            )
    return candidates, size_by_dir, unavailable


def _shard_roots_and_watch_paths(
    project_names: tuple[str, ...],
    *,
    projects_root: Path,
    now: datetime,
) -> tuple[list[str], list[str]]:
    roots: list[str] = []
    watched: list[str] = []
    for project in project_names:
        workflow_dir = projects_root / project / "artifacts" / ACE_RUN_WORKFLOW_DIR
        if not workflow_dir.is_dir():
            continue
        roots.append(str(workflow_dir))
        watched.extend(
            str(path)
            for path in iter_startup_ace_run_shard_watch_paths(workflow_dir, now=now)
        )
    return roots, watched


def _shard_kind(path: Path) -> str:
    name = path.name
    if is_agent_artifact_dir_name(name):
        return "run"
    if is_ace_run_day_shard_name(name):
        return "day"
    if len(name) == 6 and name.isdigit():
        return "month"
    return "other"


def _project_for_path(
    path: Path, project_names: tuple[str, ...], projects_root: Path
) -> str:
    normalized = _normalized_path(path)
    for project in project_names:
        prefix = _normalized_path(projects_root / project)
        if normalized == prefix or normalized.startswith(prefix + os.sep):
            return project
    return ""


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
    scan_unavailable: bool,
    continuation_unavailable: bool = False,
    continuation_reasons: Sequence[str] = (),
) -> list[str]:
    reasons: list[str] = []
    normalized_dir = _normalized_path(artifact_dir)
    if continuation_unavailable:
        reasons.append("continuation_unavailable")
    if continuation_reasons:
        reasons.extend(continuation_reasons)
    if normalized_dir in protections.protected_dirs:
        reasons.append("referenced_dir")
    if timestamp in protections.protected_timestamps:
        reasons.append("referenced_timestamp")
    if _normalized_path(os.getenv("SASE_ARTIFACTS_DIR") or "") == normalized_dir:
        reasons.append("current_agent")
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
