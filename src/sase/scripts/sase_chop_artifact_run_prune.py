#!/usr/bin/env python3
"""Hourly ACE-run retention preview and expired-trash purge chop."""

from __future__ import annotations

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_prune_publish import publish_run_prune_preview
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.agent_artifact_run_trash import purge_ace_run_trash
from sase.core.time import local_now


@builtin_chop("artifact_run_prune")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    policy = AceRunRetentionPolicy(
        now=local_now(),
        keep_recent_months=get_artifact_retention_keep_recent_run_months(),
    )
    protections = collect_ace_run_retention_protections(
        projects_root=policy.projects_root
    )

    # The confirmation authorizes eventual reclamation. Purge expired trash on
    # every hourly tick, even when new automatic retention is disabled.
    purge_failed = False
    try:
        purge = purge_ace_run_trash(protections, projects_root=policy.projects_root)
        runtime.log(
            "artifact_run_prune trash purge: "
            f"purged={purge.purged}, restored={purge.restored}, "
            f"freed_bytes={purge.freed_bytes}"
        )
        if purge.blocked_reason == "busy":
            runtime.log(
                "artifact_run_prune: trash lock busy; preview notification skipped"
            )
        elif purge.blocked_reason or purge.errors or purge.index_errors:
            purge_failed = True
            runtime.log.warning(
                "artifact_run_prune trash purge had errors: "
                f"blocked={purge.blocked_reason}, errors={purge.errors}, "
                f"index_errors={len(purge.index_errors)}"
            )
    except Exception as exc:  # noqa: BLE001 - preview remains useful on purge failure.
        purge_failed = True
        runtime.log.warning(f"artifact_run_prune trash purge failed: {exc}")
        purge = None

    plan = plan_ace_run_retention(policy, protections=protections)
    if plan.counts.selected or plan.counts.empty_out_of_range_shards:
        runtime.log(
            "artifact_run_prune preview: "
            f"{plan.counts.selected} run dir(s), "
            f"{plan.counts.empty_out_of_range_shards} empty shard(s), "
            f"{plan.reclaimable_bytes} byte(s) reclaimable"
        )
    for source in plan.sources_unavailable:
        runtime.log.warning(
            f"artifact_run_prune protection source unavailable: {source}"
        )

    if not (purge and purge.blocked_reason == "busy"):
        publish_run_prune_preview(plan)

    reason = _reason_for(plan)
    if reason is None and purge and purge.blocked_reason == "busy":
        reason = "prune_in_progress"
    result = runtime.emit_summary(
        {
            "candidates": plan.counts.candidates,
            "selected": plan.counts.selected,
            "empty_shards": plan.counts.empty_out_of_range_shards,
            "bytes": plan.reclaimable_bytes,
            "protected": plan.counts.protected,
            "unavailable": len(plan.sources_unavailable),
            "purged_batches": purge.purged if purge else 0,
            "restored_runs": purge.restored if purge else 0,
            "freed_bytes": purge.freed_bytes if purge else 0,
        },
        reason=reason,
    )
    if plan.sources_unavailable or purge_failed:
        result.status = "check_error"
    return result


def _reason_for(plan: AceRunRetentionPlan) -> str | None:
    counts = plan.counts
    if plan.sources_unavailable:
        return "protection_unavailable"
    if not counts.selected and not counts.empty_out_of_range_shards:
        return "nothing_reclaimable"
    return None


def main() -> None:
    run_builtin_chop("artifact_run_prune")


if __name__ == "__main__":
    main()
