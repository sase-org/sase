#!/usr/bin/env python3
"""Hourly ACE-run retention preview and expired-trash purge chop."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sase.chops import ChopReport
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.config import (
    get_artifact_retention_keep_recent_run_months,
)
from sase.core.agent_artifact_run_prune_review import (
    build_review,
    encode_run_prune_review,
    preview_fingerprint,
    write_snapshot,
)
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.agent_artifact_run_trash import purge_ace_run_trash
from sase.core.time import get_timezone, local_now
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import upsert_notification
from sase.project_display_names import load_project_ref_display_snapshot

_NOTIFICATION_SENDER = "axe"
_NOTIFICATION_TAGS = ("artifact-retention", "ace-run", "preview")
_PREVIEW_COMMAND = "sase artifact prune-runs"
_LAST_PREVIEW_KEY = "last_preview_dedup_key"


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

    if _should_notify(plan) and not (purge and purge.blocked_reason == "busy"):
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


def _should_notify(plan: AceRunRetentionPlan) -> bool:
    counts = plan.counts
    return bool(
        counts.selected or counts.empty_out_of_range_shards or plan.sources_unavailable
    )


def _notify_actionable_preview(plan: AceRunRetentionPlan) -> None:
    timestamp = datetime.now(get_timezone()).isoformat()
    fingerprint = preview_fingerprint(plan)
    _, snapshot_path = write_snapshot(plan, captured_at=datetime.now(get_timezone()))
    review = build_review(plan, fingerprint=fingerprint)
    previous_key = _read_last_preview_key(snapshot_path.parent)
    dedup_key = f"artifact_run_prune:{fingerprint}"
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_NOTIFICATION_SENDER,
        icon="!" if plan.sources_unavailable else "🧹",
        color="#D14343" if plan.sources_unavailable else "#2F80ED",
        notes=_notification_notes(plan),
        tags=normalize_notification_tags(_NOTIFICATION_TAGS),
        action="ViewReport",
        action_data={
            "report_title": "ACE run pruning preview",
            "report": json.dumps(_preview_report(plan).to_dict(), sort_keys=True),
            "preview_command": _PREVIEW_COMMAND,
            "run_prune_review": encode_run_prune_review(review),
        },
        dedup_key=dedup_key,
    )
    upsert_notification(
        notification,
        plus_one_note=_plus_one_note(plan),
        plus_one_timestamp=timestamp,
        supersedes=previous_key if previous_key != dedup_key else None,
    )
    _write_last_preview_key(snapshot_path.parent, dedup_key)


def _notification_notes(plan: AceRunRetentionPlan) -> list[str]:
    counts = plan.counts
    if plan.sources_unavailable:
        return [
            "ACE run pruning is paused",
            (
                f"{len(plan.sources_unavailable)} protection sources are unreadable; "
                "nothing will be pruned until they recover."
            ),
            "Press Enter for details.",
        ]
    return [
        f"{_human_size(plan.reclaimable_bytes)} of old ACE runs can be pruned",
        (
            f"{counts.selected:,} runs · {len(build_review(plan).projects)} projects · "
            f"older than {_month_label(build_review(plan).first_kept_month)} · "
            f"{counts.protected:,} protected"
        ),
        "Press Enter to review — runs move to a 14-day restorable trash.",
    ]


def _plus_one_note(plan: AceRunRetentionPlan) -> str:
    if plan.sources_unavailable:
        return f"Still paused: {len(plan.sources_unavailable)} protection sources are unreadable."
    return (
        f"Still available: {_human_size(plan.reclaimable_bytes)} across "
        f"{plan.counts.selected:,} runs."
    )


def _preview_report(plan: AceRunRetentionPlan) -> ChopReport:
    counts = plan.counts
    review = build_review(plan)
    display = load_project_ref_display_snapshot(projects_root=plan.policy.projects_root)
    report = ChopReport(title="ACE run pruning preview")
    if plan.sources_unavailable:
        report.headline("ACE run pruning is paused", tone="warn")
    else:
        report.headline(
            f"{counts.selected:,} old ACE runs · "
            f"{_human_size(plan.reclaimable_bytes)} reclaimable",
            tone="info",
        )
    report.kv(
        {
            "Runs": f"{counts.selected:,}",
            "Reclaimable": _human_size(plan.reclaimable_bytes),
            "Projects": str(len(review.projects)),
            "Protected": f"{counts.protected:,}",
            "Keeping": f"newest {plan.policy.keep_recent_months} months",
        }
    )
    if plan.sources_unavailable:
        report.heading("Protection Problems")
        report.bullets(tuple(plan.sources_unavailable[:12]), tone="warn", glyph="!")
    if review.projects:
        rows = report.rows(columns=("Project", "Runs", "Size", "Span"))
        for project in review.projects:
            rows.row(
                (
                    display.label_for_ref(project.project) or project.project,
                    f"{project.runs:,}",
                    _human_size(project.bytes),
                    f"{_format_timestamp(project.oldest)} – "
                    f"{_format_timestamp(project.newest)}",
                )
            )
    if plan.empty_out_of_range_shards:
        report.heading("Empty shards")
        rows = report.rows(columns=("Project", "Kind", "Path"))
        for shard in plan.empty_out_of_range_shards[:10]:
            shard_project = shard.project or "-"
            rows.row(
                (
                    display.label_for_ref(shard_project) or shard_project,
                    shard.kind,
                    shard.path,
                )
            )
    if plan.sources_unavailable:
        report.text("Press Enter for details.", tone="muted")
    else:
        report.text(
            "Enter: review and move to trash (restorable 14 days)", tone="muted"
        )
        report.text(f"CLI: {_PREVIEW_COMMAND} --apply", tone="muted")
    return report


def _read_last_preview_key(directory: Path) -> str | None:
    try:
        value = (directory / _LAST_PREVIEW_KEY).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _write_last_preview_key(directory: Path, value: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".preview-key.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / _LAST_PREVIEW_KEY)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def _format_timestamp(timestamp: str) -> str:
    try:
        moment = datetime.strptime(timestamp[:8], "%Y%m%d")
    except ValueError:
        return timestamp
    return moment.strftime("%b %-d")


def _month_label(month: str) -> str:
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return month


def main() -> None:
    run_builtin_chop("artifact_run_prune")


if __name__ == "__main__":
    main()
