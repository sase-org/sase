"""Candidate scan and protection reasons for ACE-run retention.

Split out of :mod:`sase.core.agent_artifact_run_retention` to keep each
module under the 500-line cap. Preview assembly and apply refusal live in
:mod:`sase.core.agent_artifact_run_retention_plan`. The public import path
remains :mod:`sase.core.agent_artifact_run_retention`.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core import continuation_retention
from sase.core._agent_artifact_run_retention_shared import (
    normalized_path,
    recent_month_names,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    iter_agent_artifact_dirs,
    parse_agent_artifact_path,
)
from sase.core.agent_artifact_run_retention_models import AceRunProtectionSnapshot
from sase.core.agent_scan_facade import scan_agent_artifact_dirs
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir


_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=(ACE_RUN_WORKFLOW_DIR,),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=True,
    include_workflow_state=True,
    include_waiting=True,
)


def plan_continuation_run_retention(
    artifact_dirs: Sequence[Path | str],
    *,
    projects_root: Path | str | None = None,
) -> dict[str, Any]:
    return continuation_retention.plan_continuation_run_retention(
        artifact_dirs, projects_root=projects_root
    )


def collect_ace_run_retention_candidates(
    protections: AceRunProtectionSnapshot,
    *,
    projects_root: Path,
    project_names: tuple[str, ...],
    now: datetime,
    keep_recent_months: int,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Scan out-of-window artifact dirs into Rust-bound candidates.

    Runs in the keep-recent window can never be selected (the Rust owner
    adds ``recent_month`` itself), so they are passed through with empty
    Python reasons and skip the record scan, continuation planning, and
    per-candidate protection checks.
    """

    unavailable: set[str] = set()
    recent_months = recent_month_names(now, keep_recent_months)
    current_artifacts_dir = normalized_path(os.getenv("SASE_ARTIFACTS_DIR") or "")
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
    # Split recent-window dirs out before any expensive scan: they need no
    # continuation planning, record scan, or protection reasons.
    out_of_window_by_project: dict[str, list[Path]] = {p: [] for p in project_names}
    is_recent: dict[str, bool] = {}
    for project in project_names:
        for artifact_dir in project_dirs[project]:
            info = parse_agent_artifact_path(artifact_dir, projects_root=projects_root)
            if info is None:
                continue
            key = str(artifact_dir)
            if info.timestamp[:6] in recent_months:
                is_recent[key] = True
            else:
                is_recent[key] = False
                out_of_window_by_project[project].append(artifact_dir)
    out_of_window_dirs = tuple(
        artifact_dir
        for project in project_names
        for artifact_dir in out_of_window_by_project[project]
    )
    continuation_reasons: dict[str, tuple[str, ...]] = {}
    continuation_unavailable = False
    try:
        continuation_plan = plan_continuation_run_retention(
            out_of_window_dirs, projects_root=projects_root
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
    records_by_project: dict[str, dict[str, AgentArtifactRecordWire]] = {}
    scan_error_by_project: dict[str, bool] = {}
    for project in project_names:
        old_dirs = tuple(out_of_window_by_project[project])
        records, scan_error = _scan_records(projects_root, old_dirs)
        if scan_error is not None:
            unavailable.add(scan_error)
        records_by_project[project] = records
        scan_error_by_project[project] = scan_error is not None
    for project in project_names:
        for artifact_dir in project_dirs[project]:
            info = parse_agent_artifact_path(artifact_dir, projects_root=projects_root)
            if info is None:
                continue
            if is_recent.get(str(artifact_dir), False):
                candidates.append(
                    {
                        "artifact_dir": str(artifact_dir),
                        "project": project,
                        "timestamp": info.timestamp,
                        "protected_reasons": [],
                    }
                )
                continue
            dir_key = normalized_path(artifact_dir)
            record = records_by_project[project].get(dir_key)
            reasons = _protection_reasons(
                project=project,
                timestamp=info.timestamp,
                artifact_dir=artifact_dir,
                record=record,
                protections=protections,
                scan_unavailable=scan_error_by_project[project],
                continuation_unavailable=continuation_unavailable,
                continuation_reasons=continuation_reasons.get(dir_key, ()),
                normalized_dir=dir_key,
                current_artifacts_dir=current_artifacts_dir,
            )
            candidates.append(
                {
                    "artifact_dir": str(artifact_dir),
                    "project": project,
                    "timestamp": info.timestamp,
                    "protected_reasons": reasons,
                }
            )
    return candidates, unavailable


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
        {normalized_path(record.artifact_dir): record for record in snapshot.records},
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
    normalized_dir: str | None = None,
    current_artifacts_dir: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    if normalized_dir is None:
        normalized_dir = normalized_path(artifact_dir)
    if current_artifacts_dir is None:
        current_artifacts_dir = normalized_path(os.getenv("SASE_ARTIFACTS_DIR") or "")
    if continuation_unavailable:
        reasons.append("continuation_unavailable")
    if continuation_reasons:
        reasons.extend(continuation_reasons)
    if normalized_dir in protections.protected_dirs:
        reasons.append("referenced_dir")
    if timestamp in protections.protected_timestamps:
        reasons.append("referenced_timestamp")
    if current_artifacts_dir == normalized_dir:
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


def protection_reasons_for_dirs(
    artifact_dirs: Sequence[Path | str],
    protections: AceRunProtectionSnapshot,
    *,
    projects_root: Path | str | None = None,
) -> dict[str, list[str]]:
    """Map each normalized artifact dir to its preview-predicate reasons.

    Uses the same per-candidate protection inputs as the preview plan, so
    quarantine re-verification cannot disagree with the preview. Reasons
    follow the preview convention; an empty list means the dir looks
    eligible right now. Directories that do not parse as ACE-run paths are
    reported with ``("invalid_run_path",)``.
    """

    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else sase_projects_dir()
    )
    dirs = tuple(Path(item).expanduser() for item in artifact_dirs)
    continuation_reasons: dict[str, tuple[str, ...]] = {}
    continuation_unavailable = False
    try:
        continuation_plan = plan_continuation_run_retention(dirs, projects_root=root)
    except ValueError:
        continuation_unavailable = True
    else:
        continuation_reasons = continuation_retention.continuation_reasons_by_dir(
            continuation_plan
        )
    records, scan_error = _scan_records(root, dirs)
    current_artifacts_dir = normalized_path(os.getenv("SASE_ARTIFACTS_DIR") or "")
    reasons_by_dir: dict[str, list[str]] = {}
    for artifact_dir in dirs:
        dir_key = normalized_path(artifact_dir)
        info = parse_agent_artifact_path(artifact_dir, projects_root=root)
        if info is None:
            reasons_by_dir[dir_key] = ["invalid_run_path"]
            continue
        item_reasons = _protection_reasons(
            project=info.project_name,
            timestamp=info.timestamp,
            artifact_dir=artifact_dir,
            record=records.get(dir_key),
            protections=protections,
            scan_unavailable=scan_error is not None,
            continuation_unavailable=continuation_unavailable,
            continuation_reasons=continuation_reasons.get(dir_key, ()),
            normalized_dir=dir_key,
            current_artifacts_dir=current_artifacts_dir,
        )
        reasons_by_dir[dir_key] = _dedupe(item_reasons)
    return reasons_by_dir


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.stat(follow_symlinks=False).st_mode)
    except OSError:
        return False


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "collect_ace_run_retention_candidates",
    "plan_continuation_run_retention",
    "protection_reasons_for_dirs",
]
