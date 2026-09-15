#!/usr/bin/env python3
"""Read-only ACE-run retention preview chop."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sase.chops import ChopReport
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
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import upsert_notification

_NOTIFICATION_SENDER = "axe"
_NOTIFICATION_TAGS = ("artifact-retention", "ace-run", "preview")
_APPLY_COMMAND = "sase artifact prune-runs --apply"
_PREVIEW_COMMAND = "sase artifact prune-runs"


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
    if _should_notify(plan):
        _notify_actionable_preview(plan)

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


def _should_notify(plan: AceRunRetentionPlan) -> bool:
    counts = plan.counts
    return bool(
        counts.selected or counts.empty_out_of_range_shards or plan.sources_unavailable
    )


def _notify_actionable_preview(plan: AceRunRetentionPlan) -> None:
    timestamp = local_now().isoformat()
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_NOTIFICATION_SENDER,
        icon="!",
        color="#D14343" if plan.sources_unavailable else "#2F80ED",
        notes=_notification_notes(plan),
        tags=normalize_notification_tags(_NOTIFICATION_TAGS),
        action="ViewReport",
        action_data={
            "report_title": "ACE run pruning preview",
            "report": json.dumps(_preview_report(plan).to_dict(), sort_keys=True),
            "preview_command": _PREVIEW_COMMAND,
            "apply_command": _APPLY_COMMAND,
        },
        dedup_key=f"artifact_run_prune:{_preview_fingerprint(plan)}",
    )
    upsert_notification(
        notification,
        plus_one_note=_plus_one_note(plan),
        plus_one_timestamp=timestamp,
    )


def _notification_notes(plan: AceRunRetentionPlan) -> list[str]:
    counts = plan.counts
    if plan.sources_unavailable:
        return [
            "ACE run pruning needs attention",
            (
                f"{len(plan.sources_unavailable)} protection source(s) are "
                "unavailable; apply is blocked until coverage is complete."
            ),
            f"Review: {_PREVIEW_COMMAND}",
        ]
    return [
        "ACE run pruning preview is available",
        (
            f"{counts.selected} run dir(s), "
            f"{counts.empty_out_of_range_shards} empty shard(s), "
            f"{_human_size(plan.reclaimable_bytes)} reclaimable."
        ),
        f"Apply explicitly: {_APPLY_COMMAND}",
    ]


def _plus_one_note(plan: AceRunRetentionPlan) -> str:
    counts = plan.counts
    if plan.sources_unavailable:
        return f"Still blocked by {len(plan.sources_unavailable)} protection source(s)."
    return (
        "Still previewing "
        f"{counts.selected} run dir(s), "
        f"{counts.empty_out_of_range_shards} empty shard(s), "
        f"{_human_size(plan.reclaimable_bytes)} reclaimable."
    )


def _preview_report(plan: AceRunRetentionPlan) -> ChopReport:
    counts = plan.counts
    report = ChopReport(title="ACE run pruning preview")
    if plan.sources_unavailable:
        report.headline("Protection coverage is incomplete", tone="warn")
    else:
        report.headline("Explicit approval can reclaim ACE run storage", tone="info")
    report.kv(
        {
            "Run dirs": str(counts.selected),
            "Empty shards": str(counts.empty_out_of_range_shards),
            "Reclaimable": _human_size(plan.reclaimable_bytes),
            "Protected": str(counts.protected),
            "Unavailable sources": str(len(plan.sources_unavailable)),
        }
    )
    if plan.sources_unavailable:
        report.heading("Protection Problems")
        report.bullets(tuple(plan.sources_unavailable[:12]), tone="warn", glyph="!")
    if plan.selected:
        rows = report.rows(columns=("Project", "Timestamp", "Size"))
        for item in plan.selected[:20]:
            rows.row((item.project, item.timestamp, _human_size(item.size_bytes)))
    if plan.empty_out_of_range_shards:
        rows = report.rows(columns=("Project", "Kind", "Path"))
        for shard in plan.empty_out_of_range_shards[:20]:
            rows.row((shard.project or "-", shard.kind, shard.path))
    report.text(f"Review command: {_PREVIEW_COMMAND}", tone="muted")
    report.text(f"Apply command: {_APPLY_COMMAND}", tone="accent")
    return report


def _preview_fingerprint(plan: AceRunRetentionPlan) -> str:
    payload = {
        "selected": [
            {
                "project": item.project,
                "timestamp": item.timestamp,
                "artifact_dir": item.artifact_dir,
                "size_bytes": item.size_bytes,
            }
            for item in plan.selected
        ],
        "empty_shards": [
            {
                "project": shard.project,
                "kind": shard.kind,
                "path": shard.path,
            }
            for shard in plan.empty_out_of_range_shards
        ],
        "sources_unavailable": list(plan.sources_unavailable),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def main() -> None:
    run_builtin_chop("artifact_run_prune")


if __name__ == "__main__":
    main()
