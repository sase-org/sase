"""Read-only inventory for ``sase plan list``."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_helpers import path_key, read_json_object
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import iter_sharded_files, sase_home, sase_projects_dir
from sase.core.time import get_timezone
from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.main.plan_inventory_models import (
    DEFAULT_HISTORY_LIMIT,
    PLAN_STATUSES,
    ApprovedPlan,
    DisplayPathRoots,
    PlanInventory,
    ProposedPlan,
    RejectedPlan,
    selected_statuses,
    tier_counts,
)
from sase.main.plan_inventory_render import (
    render_plan_inventory as _render_plan_inventory,
)
from sase.notifications.models import Notification, format_relative_time
from sase.notifications.pending_actions import PENDING_ACTION_PREFIX_LEN
from sase.project_display_names import project_display_name_for

_APPROVED_META_CANDIDATE_LIMIT = 2_000


def build_plan_inventory(
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    tiers: tuple[str, ...] = (),
    statuses: tuple[str, ...] = (),
) -> PlanInventory:
    """Build the current plan proposal/approval inventory."""
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    display_roots = _display_path_roots()
    tier_set = set(tiers)
    status_filter = _normalize_statuses(statuses)
    proposed = _collect_proposed_plans(display_roots=display_roots)
    approved, approved_scan_truncated = _collect_approved_plans(
        limit=limit,
        display_roots=display_roots,
        tiers=tier_set,
    )

    # Collect approvals even when their section is filtered out. A larger
    # history limit also makes rejected inference more accurate by recognizing
    # more archived plans as represented.
    represented_paths = {row._plan_key for row in proposed if row._plan_key} | {
        row._plan_key for row in approved if row._plan_key
    }
    archived_paths = _archived_plan_paths()
    rejected = _collect_rejected_plans(
        archived_paths,
        represented_paths=represented_paths,
        limit=limit,
        display_roots=display_roots,
        tiers=tier_set,
    )

    if tier_set:
        proposed = tuple(row for row in proposed if row.tier in tier_set)

    return PlanInventory(
        proposed=proposed,
        approved=approved,
        rejected=rejected,
        total_archived_proposals=len(archived_paths),
        tier_filter=tiers,
        status_filter=status_filter,
        limit=limit,
        approved_scan_truncated=approved_scan_truncated,
    )


def plan_inventory_to_json(inventory: PlanInventory) -> dict[str, object]:
    """Return a stable JSON projection for a plan inventory."""
    summary: dict[str, object] = {
        "proposed": len(inventory.proposed),
        "approved_shown": len(inventory.approved),
        "rejected_shown": len(inventory.rejected),
        "total_archived_proposals": inventory.total_archived_proposals,
    }
    if inventory.status_filter:
        summary["status_filter"] = list(inventory.status_filter)
    if inventory.tier_filter:
        summary["tier_filter"] = list(inventory.tier_filter)
        summary["by_tier"] = tier_counts(inventory)
    if inventory.limit != DEFAULT_HISTORY_LIMIT:
        summary["limit"] = inventory.limit
    if inventory.approved_scan_truncated:
        summary["approved_scan_truncated"] = True

    selected = selected_statuses(inventory)
    payload: dict[str, object] = {"summary": summary}
    if "proposed" in selected:
        payload["proposed"] = [_public_row_dict(row) for row in inventory.proposed]
    if "approved" in selected:
        payload["approved"] = [_public_row_dict(row) for row in inventory.approved]
    if "rejected" in selected:
        payload["rejected"] = [asdict(row) for row in inventory.rejected]
    return payload


def render_plan_inventory(
    inventory: PlanInventory, *, console: Any | None = None
) -> None:
    """Render the inventory as a compact Rich dashboard."""
    _render_plan_inventory(
        inventory,
        console=console,
        approved_candidate_limit=_approved_candidate_limit,
        agent_project=_agent_project,
    )


def _collect_proposed_plans(
    *,
    display_roots: DisplayPathRoots,
) -> tuple[ProposedPlan, ...]:
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
        plan_path=_display_path(plan_path, display_roots=display_roots),
        tier=_tier_for_path(plan_path),
        response_dir=_display_path(
            action_data.get("response_dir"),
            display_roots=display_roots,
        ),
    )


def _collect_approved_plans(
    *,
    limit: int,
    display_roots: DisplayPathRoots,
    tiers: set[str],
) -> tuple[tuple[ApprovedPlan, ...], bool]:
    target = limit if limit > 0 else None
    candidate_limit = _approved_candidate_limit(limit)
    meta_paths = _agent_meta_paths_newest_first()

    by_plan_key: dict[str, tuple[datetime, ApprovedPlan]] = {}
    paths_to_scan = (
        meta_paths if candidate_limit is None else meta_paths[:candidate_limit]
    )
    for meta_path in paths_to_scan:
        meta = read_json_object(meta_path)
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
        plan_path=_display_path(plan_path, display_roots=display_roots),
        tier=_tier_for_path(plan_path),
        meta_path=_display_path(str(meta_path), display_roots=display_roots),
    )


def _collect_rejected_plans(
    archived_paths: tuple[Path, ...],
    *,
    represented_paths: set[str],
    limit: int,
    display_roots: DisplayPathRoots,
    tiers: set[str],
) -> tuple[RejectedPlan, ...]:
    rows: list[tuple[datetime, RejectedPlan]] = []
    for path in archived_paths:
        if path_key(path) in represented_paths:
            continue
        timestamp = _file_mtime(path)
        timestamp_text = timestamp.isoformat()
        tier = _tier_for_path(str(path))
        if tiers and tier not in tiers:
            continue
        rows.append(
            (
                timestamp,
                RejectedPlan(
                    timestamp=timestamp_text,
                    age=format_relative_time(timestamp_text),
                    plan_path=_display_path(str(path), display_roots=display_roots),
                    tier=tier,
                ),
            )
        )
    sorted_rows = sorted(rows, key=lambda item: item[0], reverse=True)
    selected_rows = sorted_rows if limit == 0 else sorted_rows[:limit]
    return tuple(row for _, row in selected_rows)


def _agent_meta_paths_newest_first() -> tuple[Path, ...]:
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


def _approved_candidate_limit(limit: int) -> int | None:
    if limit == 0:
        return None
    return max(_APPROVED_META_CANDIDATE_LIMIT, 100 * limit)


def _normalize_statuses(statuses: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(status.strip().lower() for status in statuses))
    invalid = [status for status in normalized if status not in PLAN_STATUSES]
    if invalid:
        raise ValueError(f"unknown plan status: {invalid[0]}")
    return normalized


def _display_path_roots() -> DisplayPathRoots:
    return DisplayPathRoots(
        sase_root=sase_home().expanduser().resolve(strict=False),
        home=Path.home().expanduser().resolve(strict=False),
    )


def _archived_plan_paths() -> tuple[Path, ...]:
    return tuple(
        path for path in iter_sharded_files("plans", pattern="*.md") if path.is_file()
    )


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


def _display_path(
    path: str | None,
    *,
    display_roots: DisplayPathRoots | None = None,
) -> str:
    if not path:
        return "-"
    roots = display_roots or _display_path_roots()
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    try:
        return f"~/.sase/{resolved.relative_to(roots.sase_root)}"
    except ValueError:
        pass

    try:
        relative = resolved.relative_to(roots.home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative}"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _tier_for_path(path: str | None) -> str:
    if not path:
        return "-"
    from sase.sdd.plan_tiers import read_plan_tier

    candidate = Path(path).expanduser()
    tier = read_plan_tier(candidate) if candidate.exists() else None
    return tier or "-"


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _public_row_dict(row: Any) -> dict[str, object]:
    return {key: value for key, value in asdict(row).items() if not key.startswith("_")}


def _agent_project(agent: str, project: str) -> str:
    if project != "-":
        project = project_display_name_for(project)
    if agent == "-" and project == "-":
        return "-"
    if agent == "-":
        return project
    if project == "-":
        return agent
    return f"{agent} / {project}"
