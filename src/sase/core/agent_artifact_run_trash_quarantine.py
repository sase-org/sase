"""Quarantine reviewed ACE runs into restorable trash.

Split out of :mod:`sase.core.agent_artifact_run_trash` to keep each
module under the 500-line cap. Listing, restore, and purge live in
:mod:`sase.core.agent_artifact_run_trash_ops`. The public import path
remains :mod:`sase.core.agent_artifact_run_trash`.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sase.config import (
    get_artifact_retention_empty_shard_removal_budget,
    get_artifact_retention_trash_grace_days,
)
from sase.core._agent_artifact_run_trash_shared import (
    call_run_trash_binding,
    normalized_dir,
    run_trash_root,
)
from sase.core.agent_artifact_index_lifecycle_mutations import (
    delete_agent_artifact_index_artifacts,
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
from sase.core.agent_artifact_run_trash_models import (
    AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
    AceRunTrashItemOutcome,
    AceRunTrashQuarantineResult,
    ReviewedRunSet,
)
from sase.core.agent_artifact_shards import (
    iter_startup_ace_run_shard_watch_paths,
)


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
    root = run_trash_root() if trash_root is None else Path(trash_root).expanduser()
    projects_root = plan.policy.normalized_projects_root()
    created_at = moment.isoformat()
    batch_id = _new_batch_id(moment)
    grace_days = get_artifact_retention_trash_grace_days()
    restorable_until = _restorable_until(moment, grace_days)

    selected_by_dir = {
        normalized_dir(item.artifact_dir): item for item in plan.selected
    }
    protected_by_dir = {
        normalized_dir(item.artifact_dir): item for item in plan.protected
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
    raw = call_run_trash_binding("quarantine_agent_artifact_runs", request)
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


__all__ = [
    "quarantine_ace_runs",
]
