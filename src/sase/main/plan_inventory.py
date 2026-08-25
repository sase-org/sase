"""Read-only inventory for ``sase plan list``."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.core.artifact_file_helpers import path_key, read_json_object
from sase.main.plan_inventory_collectors import (
    agent_meta_paths_newest_first,
    approved_candidate_limit,
    collect_approved_plans,
    collect_proposed_plans,
    collect_rejected_plans,
)
from sase.main.plan_inventory_models import (
    DEFAULT_HISTORY_LIMIT,
    PLAN_STATUSES,
    ApprovedPlan,
    DisplayPathRoots,
    PlanInventory,
    selected_statuses,
    tier_counts,
)
from sase.main.plan_inventory_paths import archived_plan_paths, display_path_roots
from sase.main.plan_inventory_render import (
    render_plan_inventory as _render_plan_inventory,
)
from sase.project_display_names import project_display_name_for

# Keep these private integration seams local to the facade. Besides making the
# orchestration readable, this preserves callers that patch them in tests.
_agent_meta_paths_newest_first = agent_meta_paths_newest_first
_approved_candidate_limit = approved_candidate_limit
_archived_plan_paths = archived_plan_paths
_collect_proposed_plans = collect_proposed_plans
_collect_rejected_plans = collect_rejected_plans
_display_path_roots = display_path_roots


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
    # more archived plans as represented. Rejected inference reads and
    # YAML-parses every unrepresented archived plan file, so skip it outright
    # when the caller did not ask for that section.
    archived_paths = _archived_plan_paths()
    if not status_filter or "rejected" in status_filter:
        represented_paths = {row._plan_key for row in proposed if row._plan_key} | {
            row._plan_key for row in approved if row._plan_key
        }
        rejected = _collect_rejected_plans(
            archived_paths,
            represented_paths=represented_paths,
            limit=limit,
            display_roots=display_roots,
            tiers=tier_set,
        )
    else:
        rejected = ()

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


def _collect_approved_plans(
    *,
    limit: int,
    display_roots: DisplayPathRoots,
    tiers: set[str],
) -> tuple[tuple[ApprovedPlan, ...], bool]:
    return collect_approved_plans(
        limit=limit,
        display_roots=display_roots,
        tiers=tiers,
        meta_paths=_agent_meta_paths_newest_first(),
        candidate_limit=_approved_candidate_limit(limit),
        read_meta=read_json_object,
    )


def _normalize_statuses(statuses: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(status.strip().lower() for status in statuses))
    invalid = [status for status in normalized if status not in PLAN_STATUSES]
    if invalid:
        raise ValueError(f"unknown plan status: {invalid[0]}")
    return normalized


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
