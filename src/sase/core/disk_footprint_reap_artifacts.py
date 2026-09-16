"""Artifact run retention owner step for ``sase disk reap``."""

from __future__ import annotations

from typing import Any

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.time import local_now


def artifact_run_reap_step(*, apply: bool, project: str | None) -> DiskReapStep:
    policy = AceRunRetentionPolicy(
        now=local_now(),
        keep_recent_months=get_artifact_retention_keep_recent_run_months(),
        project=project,
    )
    try:
        protections = collect_ace_run_retention_protections(
            projects_root=policy.projects_root
        )
        plan = plan_ace_run_retention(policy, protections=protections)
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary=f"could not plan artifact run retention: {exc}",
            command=("sase", "artifact", "prune-runs", "--apply"),
        )
    if plan.sources_unavailable and not apply:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary=(
                "protection sources unavailable: " + ", ".join(plan.sources_unavailable)
            ),
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
            exit_code=1,
            details={"sources_unavailable": list(plan.sources_unavailable)},
        )
    if not apply:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="dry_run",
            summary=(
                f"would remove {plan.counts.selected} run dir(s) and "
                f"{plan.counts.empty_out_of_range_shards} empty shard(s)"
            ),
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
            details={
                "selected_runs": plan.counts.selected,
                "empty_out_of_range_shards": plan.counts.empty_out_of_range_shards,
                "sources_unavailable": list(plan.sources_unavailable),
            },
        )
    try:
        execution = apply_ace_run_retention(plan)
    except Exception as exc:  # noqa: BLE001 - report owner failure as a step.
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="error",
            summary=f"artifact run retention failed: {exc}",
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
            exit_code=1,
        )
    details = {
        "removed_runs": execution.removed_runs,
        "removed_empty_shards": execution.removed_empty_shards,
        "bytes_reclaimed": execution.bytes_reclaimed,
        "deindexed": execution.deindexed,
        "skipped": list(execution.skipped),
        "errors": list(execution.errors),
        "preview_reclaimable_bytes": plan.reclaimable_bytes,
        "sources_unavailable": list(plan.sources_unavailable),
    }
    if execution.errors:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary="; ".join(execution.errors),
            reclaimed_bytes=execution.bytes_reclaimed,
            changed=bool(execution.removed_runs or execution.removed_empty_shards),
            command=("sase", "artifact", "prune-runs", "--apply"),
            exit_code=1,
            blocked_reason="; ".join(execution.errors),
            details=details,
        )
    return DiskReapStep(
        owner="artifact_run_retention",
        mode="apply",
        summary=_artifact_execution_summary(execution),
        reclaimed_bytes=execution.bytes_reclaimed,
        changed=bool(execution.removed_runs or execution.removed_empty_shards),
        command=("sase", "artifact", "prune-runs", "--apply"),
        details=details,
    )


def _artifact_execution_summary(execution: Any) -> str:
    suffix = ""
    if execution.skipped:
        suffix += f", skipped {len(execution.skipped)}"
    if execution.errors:
        suffix += f", errors {len(execution.errors)}"
    return (
        f"removed {execution.removed_runs} run dir(s), "
        f"{execution.removed_empty_shards} empty shard(s){suffix}"
    )


__all__ = ["artifact_run_reap_step"]
