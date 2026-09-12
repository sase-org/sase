#!/usr/bin/env python3
"""Read-only ACE-run retention preview chop."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
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

    reason = _reason_for(plan)
    result = runtime.emit_summary(
        {
            "candidates": plan.counts.candidates,
            "selected": plan.counts.selected,
            "empty_shards": plan.counts.empty_out_of_range_shards,
            "bytes": plan.reclaimable_bytes,
            "protected": plan.counts.protected,
            "unavailable": len(plan.sources_unavailable),
        },
        reason=reason,
    )
    if plan.sources_unavailable:
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
