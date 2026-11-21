"""Preview assembly and apply refusal for ACE-run retention.

Split out of :mod:`sase.core.agent_artifact_run_retention` to keep each
module under the 500-line cap. Candidate scan and protection reasons live
in :mod:`sase.core.agent_artifact_run_retention_candidates`. The public
import path remains :mod:`sase.core.agent_artifact_run_retention`.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_empty_shard_removal_budget
from sase.core._agent_artifact_run_retention_shared import (
    normalized_path,
    recent_month_names,
)
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_artifact_run_protection import (
    collect_ace_run_retention_protections,
)
from sase.core.agent_artifact_run_retention_candidates import (
    collect_ace_run_retention_candidates,
)
from sase.core.agent_artifact_run_retention_models import (
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
from sase.core.paths import is_valid_sase_project_name
from sase.core.rust import require_rust_binding


_RUN_RETENTION_WIRE_SCHEMA_VERSION = 3


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
    sources_unavailable, result = _run_owner(
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
        project_names=project_names,
        projects_root=projects_root,
        extra_sources_unavailable=sources_unavailable,
    )


def apply_ace_run_retention(
    plan: AceRunRetentionPlan,
    *,
    index_path: Path | str | None = None,
) -> AceRunRetentionApplyResult:
    """Refuse mutation of ACE-run directories and empty shards."""

    del index_path
    policy = plan.policy
    result = _call_rust(
        {
            "schema_version": _RUN_RETENTION_WIRE_SCHEMA_VERSION,
            "projects_root": str(policy.normalized_projects_root()),
            "recent_months": [],
            "current_timestamp": policy.now.strftime("%Y%m%d%H%M%S"),
            "limit": policy.limit,
            "apply": True,
            "sources_unavailable": [],
            "protected_dirs": [],
            "protected_timestamps": [],
            "candidates": [],
            "empty_shard_roots": [],
            "empty_shard_watched_paths": [],
            "empty_shard_removal_budget": 0,
        }
    )
    blocked_reason = str(
        result.get("blocked_reason") or "authoritative_protection_unavailable"
    )
    return AceRunRetentionApplyResult(
        removed_runs=0,
        removed_empty_shards=0,
        bytes_reclaimed=0,
        deindexed=0,
        skipped=(),
        errors=(f"apply refused: {blocked_reason}",),
    )


def _run_owner(
    policy: AceRunRetentionPolicy,
    protections: AceRunProtectionSnapshot,
    *,
    projects_root: Path,
    project_names: tuple[str, ...],
    apply: bool,
) -> tuple[list[str], dict[str, Any]]:
    """Scan candidates fresh and call the Rust run-retention owner.

    Returns the sources this scan pass found unavailable and the owner's
    raw result dict. Directory sizes are measured later, only for selected
    runs (see ``_plan_from_result``).
    """

    candidates, scan_unavailable = collect_ace_run_retention_candidates(
        protections,
        projects_root=projects_root,
        project_names=project_names,
        now=policy.now,
        keep_recent_months=policy.keep_recent_months,
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
        "recent_months": list(
            recent_month_names(policy.now, policy.keep_recent_months)
        ),
        "current_timestamp": policy.now.strftime("%Y%m%d%H%M%S"),
        "limit": policy.limit,
        "apply": apply,
        "sources_unavailable": sources_unavailable,
        "protected_dirs": sorted(protections.protected_dirs),
        "protected_timestamps": sorted(protections.protected_timestamps),
        "candidates": candidates,
        "empty_shard_roots": empty_shard_roots,
        "empty_shard_watched_paths": empty_shard_watched_paths,
        "empty_shard_removal_budget": get_artifact_retention_empty_shard_removal_budget(),
    }
    result = _call_rust(request)
    return sources_unavailable, result


def _plan_from_result(
    policy: AceRunRetentionPolicy,
    protections: AceRunProtectionSnapshot,
    result: dict[str, Any],
    *,
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
            size_bytes = _tree_size(Path(artifact_dir))
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
    resolved = normalized_path(path)
    for project in project_names:
        prefix = normalized_path(projects_root / project)
        if resolved == prefix or resolved.startswith(prefix + os.sep):
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


__all__ = [
    "apply_ace_run_retention",
    "plan_ace_run_retention",
]
