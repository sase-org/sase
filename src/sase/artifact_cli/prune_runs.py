"""Implementation of dry-run-first ``sase artifact prune-runs``."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.chops import ChopReport
from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_prune_review import (
    RunPruneSnapshot,
    human_size,
    load_snapshot,
    project_label_or_unavailable,
)
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.agent_artifact_run_trash import (
    AceRunTrashItemOutcome,
    AceRunTrashQuarantineResult,
    ReviewedRunSet,
    quarantine_ace_runs,
)
from sase.core.time import get_timezone
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import (
    load_notifications,
    mark_dismissed,
    upsert_notification,
)
from sase.ops.commands.artifact import emit_artifact_prune_runs_result
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)


ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION = 2

_RESULT_TAGS = ("artifact-retention", "ace-run", "trash")
_PREVIEW_DEDUP_PREFIX = "artifact_run_prune:"
_PREVIEW_SENDER = "axe"
_RESULT_COLOR_COMPLETE = "#2E9E5B"
_RESULT_COLOR_PARTIAL = "#C98A1B"


def handle_prune_runs(args: argparse.Namespace) -> int:
    """Plan ACE-run retention and quarantine on explicit ``--apply``."""

    snapshot_fp = getattr(args, "snapshot", None)
    apply = bool(getattr(args, "apply", False))
    if snapshot_fp is not None and not apply:
        print(
            "Error: --snapshot requires --apply; snapshots only restrict an apply.",
            file=sys.stderr,
        )
        return 2

    projects_root = (
        Path(args.projects_root).expanduser()
        if getattr(args, "projects_root", None)
        else None
    )
    projects = load_project_ref_display_snapshot(projects_root=projects_root)
    raw_project = getattr(args, "project", None)
    project = None if raw_project is None else projects.project_key_for_ref(raw_project)
    if raw_project is not None and project is None:
        print(f"Error: unknown project reference: {raw_project}", file=sys.stderr)
        return 2

    months = getattr(args, "keep_recent_months", None)
    policy = AceRunRetentionPolicy(
        now=datetime.now(get_timezone()),
        keep_recent_months=(
            get_artifact_retention_keep_recent_run_months()
            if months is None
            else months
        ),
        project=project,
        limit=None
        if getattr(args, "limit", None) == 0
        else getattr(args, "limit", None),
        projects_root=projects_root,
    )
    index_path = (
        Path(args.index_path).expanduser()
        if getattr(args, "index_path", None)
        else None
    )
    protections = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=index_path,
    )
    plan = plan_ace_run_retention(policy, protections=protections)

    reviewed: ReviewedRunSet | None = None
    snapshot_block: dict[str, object] | None = None
    if snapshot_fp is not None:
        snapshot: RunPruneSnapshot | None = load_snapshot(str(snapshot_fp))
        if snapshot is None:
            return _finish_snapshot_unavailable(args, plan)
        reviewed = snapshot.to_reviewed()

    execution: AceRunTrashQuarantineResult | None = None
    if apply:
        execution = quarantine_ace_runs(
            plan,
            protections,
            reviewed=reviewed,
            index_path=index_path,
        )
        snapshot_block = _snapshot_block(plan, reviewed=reviewed, execution=execution)
        _emit_typed_result(execution)
        if bool(getattr(args, "notify", False)):
            _notify_result(execution, projects=projects)

    payload = {
        "schema_version": ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION,
        "mode": "apply" if apply else "dry_run",
        "blocked": bool(execution is not None and execution.blocked_reason is not None),
        "plan": plan.to_json_dict(),
        "execution": None if execution is None else execution.to_json_dict(),
        "snapshot": snapshot_block,
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_text_result(
            plan,
            projects=projects,
            console=Console(),
            execution=execution,
        )
    if execution is None:
        return 0
    if execution.blocked_reason is not None or execution.errors > 0:
        return 1
    return 0


def _finish_snapshot_unavailable(
    args: argparse.Namespace, plan: AceRunRetentionPlan
) -> int:
    """Report a missing snapshot with no mutation and exit 2."""

    payload = {
        "schema_version": ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION,
        "mode": "apply",
        "blocked": True,
        "blocked_reason": "snapshot_unavailable",
        "plan": plan.to_json_dict(),
        "execution": None,
        "snapshot": None,
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        Console().print(
            "[red]blocked: snapshot_unavailable[/red] "
            "No snapshot with that fingerprint exists; nothing moved."
        )
    return 2


def _snapshot_block(
    plan: AceRunRetentionPlan,
    *,
    reviewed: ReviewedRunSet | None,
    execution: AceRunTrashQuarantineResult,
) -> dict[str, object]:
    if reviewed is None:
        return {
            "fingerprint": None,
            "reviewed": 0,
            "eligible_now": len(plan.selected),
            "not_reviewed": execution.not_reviewed,
        }
    eligible_now = sum(
        1
        for item in plan.selected
        if str(Path(item.artifact_dir).expanduser().resolve(strict=False))
        in reviewed.dirs
    )
    return {
        "fingerprint": reviewed.fingerprint,
        "reviewed": len(reviewed.dirs),
        "eligible_now": eligible_now,
        "not_reviewed": execution.not_reviewed,
    }


def _emit_typed_result(execution: AceRunTrashQuarantineResult) -> None:
    success = execution.blocked_reason is None and execution.errors == 0
    if execution.blocked_reason is not None:
        message = f"prune-runs blocked: {execution.blocked_reason}"
    else:
        message = (
            f"Moved {execution.quarantined} run dirs "
            f"({human_size(execution.bytes_quarantined)} Quarantined) to trash "
            f"as batch {execution.batch_id}."
        )
    emit_artifact_prune_runs_result(
        success=success,
        message=message,
        payload={
            "batch_id": execution.batch_id,
            "quarantined": execution.quarantined,
            "bytes": execution.bytes_quarantined,
            "kept": execution.kept,
            "kept_by_reason": dict(execution.kept_by_reason),
            "restorable_until": execution.restorable_until,
            "blocked_reason": execution.blocked_reason,
            "index_errors": list(execution.index_errors),
        },
    )


def _notify_result(
    execution: AceRunTrashQuarantineResult,
    *,
    projects: ProjectRefDisplaySnapshot,
) -> None:
    """Publish the result row, then retire live preview rows.

    Previews stay when the apply is blocked or the result upsert fails.
    Notification write failures are logged to stderr and never change the
    exit code or the filesystem outcome.
    """

    try:
        notification = _result_notification(execution, projects=projects)
        upsert_notification(
            notification,
            plus_one_note=(
                f"Still holding batch {execution.batch_id} in trash "
                f"(restorable until {execution.restorable_until})."
            ),
            plus_one_timestamp=notification.timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - notify must not fail the apply.
        print(f"Warning: prune-runs notification failed: {exc}", file=sys.stderr)
        return
    if execution.blocked_reason is None:
        _dismiss_live_previews()


def _dismiss_live_previews() -> None:
    try:
        rows = load_notifications(include_dismissed=True)
    except Exception as exc:  # noqa: BLE001 - dismissal is best effort.
        print(f"Warning: cannot list notifications to retire: {exc}", file=sys.stderr)
        return
    for row in rows:
        if row.dismissed or row.sender != _PREVIEW_SENDER:
            continue
        if not (row.dedup_key or "").startswith(_PREVIEW_DEDUP_PREFIX):
            continue
        try:
            mark_dismissed(row.id)
        except Exception as exc:  # noqa: BLE001 - keep retiring the rest.
            print(f"Warning: cannot dismiss preview {row.id}: {exc}", file=sys.stderr)


def _result_notification(
    execution: AceRunTrashQuarantineResult,
    *,
    projects: ProjectRefDisplaySnapshot,
) -> Notification:
    partial = execution.status == "partial" or execution.errors > 0
    if execution.blocked_reason is not None:
        headline = f"ACE run trash blocked: {execution.blocked_reason}"
    else:
        headline = (
            f"Moved {execution.quarantined} ACE runs to trash "
            f"({human_size(execution.bytes_quarantined)})"
        )
    report = ChopReport(title="ACE runs moved to trash")
    report.headline(headline, tone="warn" if partial else "ok")
    report.kv(
        {
            "Runs": f"{execution.quarantined}",
            "Size": human_size(execution.bytes_quarantined),
            "Batch": execution.batch_id,
            "Restorable until": execution.restorable_until,
            "Kept": f"{execution.kept}",
        }
    )
    moved: list[AceRunTrashItemOutcome] = [
        item for item in execution.items if item.outcome == "quarantined"
    ]
    if moved:
        by_project: dict[str, dict[str, int]] = {}
        for item in moved:
            rollup = by_project.setdefault(item.project, {"runs": 0, "bytes": 0})
            rollup["runs"] += 1
            rollup["bytes"] += item.bytes
        rows = report.rows(columns=("Project", "Runs", "Size"))
        for key, rollup in sorted(
            by_project.items(), key=lambda kv: (-kv[1]["bytes"], kv[0])
        ):
            rows.row(
                (
                    project_label_or_unavailable(projects, key),
                    f"{rollup['runs']}",
                    human_size(rollup["bytes"]),
                )
            )
    if execution.kept_by_reason:
        report.heading("Kept")
        report.bullets(
            tuple(
                f"{count} kept ({reason})"
                for reason, count in sorted(
                    execution.kept_by_reason.items(), key=lambda kv: (-kv[1], kv[0])
                )
            )
        )
    report.text(
        f"Restore: sase artifact trash restore runs:{execution.batch_id}",
        tone="muted",
    )
    timestamp = datetime.now(get_timezone()).isoformat()
    return Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_PREVIEW_SENDER,
        icon="🧹",
        color=_RESULT_COLOR_PARTIAL if partial else _RESULT_COLOR_COMPLETE,
        notes=[
            headline,
            (
                f"{execution.quarantined} runs "
                f"({human_size(execution.bytes_quarantined)}) in batch "
                f"{execution.batch_id}; restorable until "
                f"{execution.restorable_until}; {execution.kept} kept."
            ),
            f"Restore: sase artifact trash restore runs:{execution.batch_id}",
        ],
        tags=normalize_notification_tags(_RESULT_TAGS),
        action="ViewReport",
        action_data={
            "report_title": "ACE runs moved to trash",
            "report": json.dumps(report.to_dict(), sort_keys=True),
        },
        dedup_key=f"artifact_run_trash:{execution.batch_id}",
    )


def _print_text_result(
    plan: AceRunRetentionPlan,
    *,
    projects: ProjectRefDisplaySnapshot,
    console: Console,
    execution: AceRunTrashQuarantineResult | None,
) -> None:
    _print_plan(plan, projects=projects, console=console)
    for source in plan.sources_unavailable:
        console.print(f"[yellow]Protection source unavailable:[/yellow] {source}")
    if execution is None:
        console.print(
            "[cyan]Dry run only; --apply moves runs to restorable trash.[/cyan]"
        )
        return
    if execution.blocked_reason is not None:
        console.print(
            f"[red]Trash blocked ({execution.blocked_reason}):[/red] nothing moved."
        )
        return
    console.print(
        Panel(
            f"Moved {execution.quarantined} run dirs "
            f"({human_size(execution.bytes_quarantined)}) to trash "
            f"· batch {execution.batch_id} "
            f"· restorable until {execution.restorable_until}",
            title="ACE Run Trash",
            border_style="green" if execution.errors == 0 else "yellow",
        )
    )
    if execution.kept_by_reason:
        kept_table = Table(
            show_header=True, header_style="bold", box=None, pad_edge=False
        )
        kept_table.add_column("REASON")
        kept_table.add_column("RUNS", justify="right")
        for reason, count in sorted(
            execution.kept_by_reason.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            kept_table.add_row(reason, f"{count:,}")
        console.print(
            Panel(kept_table, title="Kept Runs by Reason", border_style="yellow")
        )
    if execution.index_errors:
        for message in execution.index_errors:
            console.print(f"[yellow]Index:[/yellow] {message}")
    console.print(
        f"[cyan]Restore:[/cyan] sase artifact trash restore runs:{execution.batch_id}"
    )


def _print_plan(
    plan: AceRunRetentionPlan,
    *,
    projects: ProjectRefDisplaySnapshot,
    console: Console,
) -> None:
    run_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    run_table.add_column("PROJECT")
    run_table.add_column("TIMESTAMP")
    run_table.add_column("SIZE", justify="right")
    run_table.add_column("REASON")
    run_table.add_column("PATH")
    for item in plan.selected:
        run_table.add_row(
            projects.display_snapshot.label_for(item.project),
            item.timestamp,
            human_size(item.size_bytes),
            item.reason,
            item.artifact_dir,
        )
    if not plan.selected:
        run_table.add_row("[dim]none[/dim]", "-", "-", "-", "-")
    title = (
        f"TUI Run Prune Plan ({plan.counts.selected} run dirs selected, "
        f"{human_size(plan.reclaimable_bytes)} reclaimable"
        f"{f', {plan.counts.truncated} truncated' if plan.counts.truncated else ''})"
    )
    console.print(Panel(run_table, title=title, border_style="cyan"))

    shard_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    shard_table.add_column("PROJECT")
    shard_table.add_column("KIND")
    shard_table.add_column("PATH")
    for shard in plan.empty_out_of_range_shards:
        shard_table.add_row(
            projects.display_snapshot.label_for(shard.project),
            shard.kind,
            shard.path,
        )
    if not plan.empty_out_of_range_shards:
        shard_table.add_row("[dim]none[/dim]", "-", "-")
    console.print(
        Panel(
            shard_table,
            title=(
                "Empty Out-of-Range Shards "
                f"({plan.counts.empty_out_of_range_shards} selected)"
            ),
            border_style="cyan",
        )
    )


__all__ = ["ARTIFACT_PRUNE_RUNS_SCHEMA_VERSION", "handle_prune_runs"]
