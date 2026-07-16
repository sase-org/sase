"""Proposal, approval, and rejection collectors for the plan inventory."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_helpers import path_key
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_projects_dir
from sase.core.time import get_timezone
from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.main.plan_inventory_models import (
    ApprovedPlan,
    DisplayPathRoots,
    ProposedPlan,
    RejectedPlan,
)
from sase.main.plan_inventory_paths import display_path, plan_metadata_for_path
from sase.notifications.models import Notification, format_relative_time
from sase.notifications.pending_actions import PENDING_ACTION_PREFIX_LEN

_APPROVED_META_CANDIDATE_LIMIT = 2_000
_ReadMeta = Callable[[Path], dict[str, Any]]


def collect_proposed_plans(
    *,
    display_roots: DisplayPathRoots,
) -> tuple[ProposedPlan, ...]:
    """Collect proposals represented by visible pending notifications."""
    notifications = visible_pending_plan_notifications()
    return tuple(
        _proposed_plan_from_notification(notification, display_roots=display_roots)
        for notification in notifications
    )


def _proposed_plan_from_notification(
    notification: Notification,
    *,
    display_roots: DisplayPathRoots,
) -> ProposedPlan:
    action_data = notification.action_data
    plan_path = _first_str(*notification.files, action_data.get("plan_file"))
    provider_model = _provider_model_label(
        action_data.get("llm_provider"),
        action_data.get("model"),
    )
    plan_metadata = plan_metadata_for_path(plan_path)
    return ProposedPlan(
        _plan_key=path_key(plan_path) if plan_path else "",
        id_prefix=notification.id[:PENDING_ACTION_PREFIX_LEN],
        notification_id=notification.id,
        timestamp=notification.timestamp,
        age=format_relative_time(notification.timestamp),
        agent=_first_str(
            action_data.get("agent_name"),
            action_data.get("agent_cl_name"),
        )
        or "-",
        project=_project_from_action_data(action_data),
        provider_model=provider_model,
        plan_path=display_path(plan_path, display_roots=display_roots),
        title=plan_metadata.title,
        tier=plan_metadata.tier,
        response_dir=display_path(
            action_data.get("response_dir"),
            display_roots=display_roots,
        ),
    )


def collect_approved_plans(
    *,
    limit: int,
    display_roots: DisplayPathRoots,
    tiers: set[str],
    meta_paths: tuple[Path, ...],
    candidate_limit: int | None,
    read_meta: _ReadMeta,
) -> tuple[tuple[ApprovedPlan, ...], bool]:
    """Collect approved plans from newest-first agent metadata paths."""
    target = limit if limit > 0 else None

    by_plan_key: dict[str, tuple[datetime, ApprovedPlan]] = {}
    paths_to_scan = (
        meta_paths if candidate_limit is None else meta_paths[:candidate_limit]
    )
    for meta_path in paths_to_scan:
        meta = read_meta(meta_path)
        if not _truthy(meta.get("plan_approved")):
            continue
        plan_path = _first_str(meta.get("plan_path"), meta.get("sdd_plan_path"))
        if not plan_path:
            continue
        timestamp = _approval_timestamp(meta, meta_path)
        row = _approved_plan_from_meta(
            meta,
            meta_path,
            plan_path,
            timestamp,
            display_roots=display_roots,
        )
        if tiers and row.tier not in tiers:
            continue
        key = path_key(plan_path)
        previous = by_plan_key.get(key)
        if previous is None or timestamp > previous[0]:
            by_plan_key[key] = (timestamp, row)
        if target is not None and len(by_plan_key) >= target:
            break

    rows = [
        row
        for _, row in sorted(
            by_plan_key.values(), key=lambda item: item[0], reverse=True
        )
    ]
    selected_rows = rows if target is None else rows[:target]
    scan_truncated = (
        target is not None
        and len(by_plan_key) < target
        and candidate_limit is not None
        and len(meta_paths) > candidate_limit
    )
    return tuple(selected_rows), scan_truncated


def _approved_plan_from_meta(
    meta: dict[str, Any],
    meta_path: Path,
    plan_path: str,
    timestamp: datetime,
    *,
    display_roots: DisplayPathRoots,
) -> ApprovedPlan:
    timestamp_text = timestamp.isoformat()
    plan_metadata = plan_metadata_for_path(plan_path)
    return ApprovedPlan(
        _plan_key=path_key(plan_path),
        timestamp=timestamp_text,
        age=format_relative_time(timestamp_text),
        action=_first_str(meta.get("plan_action")) or "approve",
        agent=_first_str(meta.get("name"), meta.get("agent_name"), meta.get("cl_name"))
        or "-",
        project=_first_str(meta.get("project"), meta.get("project_name"))
        or _project_from_meta_path(meta_path),
        provider_model=_provider_model_label(
            _first_str(meta.get("llm_provider"), meta.get("provider")),
            _first_str(meta.get("model")),
        ),
        plan_path=display_path(plan_path, display_roots=display_roots),
        title=plan_metadata.title,
        tier=plan_metadata.tier,
        meta_path=display_path(str(meta_path), display_roots=display_roots),
    )


def collect_rejected_plans(
    archived_paths: tuple[Path, ...],
    *,
    represented_paths: set[str],
    limit: int,
    display_roots: DisplayPathRoots,
    tiers: set[str],
) -> tuple[RejectedPlan, ...]:
    """Infer rejected plans from unrepresented archived proposals."""
    rows: list[tuple[datetime, RejectedPlan]] = []
    for path in archived_paths:
        if path_key(path) in represented_paths:
            continue
        timestamp = _file_mtime(path)
        timestamp_text = timestamp.isoformat()
        plan_metadata = plan_metadata_for_path(str(path))
        if tiers and plan_metadata.tier not in tiers:
            continue
        rows.append(
            (
                timestamp,
                RejectedPlan(
                    timestamp=timestamp_text,
                    age=format_relative_time(timestamp_text),
                    plan_path=display_path(str(path), display_roots=display_roots),
                    title=plan_metadata.title,
                    tier=plan_metadata.tier,
                ),
            )
        )
    sorted_rows = sorted(rows, key=lambda item: item[0], reverse=True)
    selected_rows = sorted_rows if limit == 0 else sorted_rows[:limit]
    return tuple(row for _, row in selected_rows)


def agent_meta_paths_newest_first() -> tuple[Path, ...]:
    """Return plan-capable agent metadata paths in newest-first order."""
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return ()
    # Artifact directory names are `YYYYmmddHHMMSS`, so newest-first ordering
    # does not require statting every historical meta file. Delegate the
    # per-workflow walk to `iter_agent_artifact_dirs` so both the legacy flat
    # layout and the day-sharded layout (`<YYYYMM>/<DD>/<timestamp>`) are seen.
    candidates: list[tuple[str, str, Path]] = []
    for project_dir in projects_dir.iterdir():
        artifacts_dir = project_dir / "artifacts"
        if not artifacts_dir.is_dir():
            continue
        for workflow_dir in artifacts_dir.iterdir():
            if not workflow_dir.is_dir():
                continue
            for artifact_dir in iter_agent_artifact_dirs(
                project_dir.name,
                workflow_dir.name,
                projects_root=projects_dir,
                newest_first=True,
            ):
                timestamp = artifact_dir.name
                if len(timestamp) != 14 or not timestamp.isdigit():
                    continue
                meta_path = artifact_dir / "agent_meta.json"
                candidates.append((timestamp, str(meta_path), meta_path))
    return tuple(path for _, _, path in sorted(candidates, reverse=True))


def approved_candidate_limit(limit: int) -> int | None:
    """Return the maximum metadata candidates to inspect for a row limit."""
    if limit == 0:
        return None
    return max(_APPROVED_META_CANDIDATE_LIMIT, 100 * limit)


def _approval_timestamp(meta: dict[str, Any], meta_path: Path) -> datetime:
    for key in ("plan_approved_at", "approved_at"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            parsed = _parse_datetime(value)
            if parsed is not None:
                return parsed
    return _file_mtime(meta_path)


def _file_mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, get_timezone())
    except OSError:
        return datetime.fromtimestamp(0, UTC)


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed


def _project_from_action_data(action_data: dict[str, str]) -> str:
    project_dir = _first_str(action_data.get("project_dir"))
    if project_dir:
        return Path(project_dir).name or project_dir
    project_file = _first_str(action_data.get("agent_project_file"))
    if project_file:
        return Path(project_file).stem or project_file
    return "-"


def _project_from_meta_path(meta_path: Path) -> str:
    projects_dir = sase_projects_dir()
    try:
        return meta_path.relative_to(projects_dir).parts[0]
    except (ValueError, IndexError):
        return "-"


def _provider_model_label(provider: str | None, model: str | None) -> str:
    if provider and model:
        return f"{provider}/{model}"
    if model:
        return model
    if provider:
        return provider
    return "-"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
