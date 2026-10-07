"""Administrative bead CLI command handlers."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.conflict_resolver import handle_resolve_conflicts_command
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    get_project,
)
from sase.bead.design_ref_repair import (
    DesignRefRepairPreview,
    plan_design_ref_repairs,
)
from sase.bead.plan_archive_doctor import (
    PlanArchiveDoctorReport,
    inspect_plan_archive_health,
    preview_plan_archive_repairs,
    render_plan_archive_health_messages,
    repair_plan_archive,
    unavailable_plan_archive_report,
)


def handle_bead_sync(args: argparse.Namespace) -> None:
    with get_project() as proj:
        if args.status:
            clean = proj.sync_is_clean()
            if clean:
                print("✓ Bead state is in sync with git")
            else:
                print("○ Bead state has uncommitted changes")
            return
        proj.sync()
        print("✓ Synced bead state to git")


def handle_bead_doctor(args: argparse.Namespace) -> None:
    plan_roots = _resolve_doctor_plan_roots()
    reference_context = _resolve_doctor_reference_context()
    fix_design_refs = bool(getattr(args, "fix_design_refs", False))
    fix_issue_prefix = bool(getattr(args, "fix_issue_prefix", False))
    fix_plan_archive = bool(getattr(args, "fix_plan_archive", False))
    fix_projection = bool(getattr(args, "fix_projection", False))
    fix_attachments = bool(getattr(args, "fix_attachments", False))
    verify_cache = bool(getattr(args, "verify_cache", False))
    assume_yes = bool(getattr(args, "yes", False))
    archive_store = _resolve_doctor_plan_archive_store(
        materialize=fix_plan_archive,
    )
    archive_report: PlanArchiveDoctorReport | None = None
    with get_project() as proj:
        projection_preview: list[dict[str, Any]] = []
        if fix_projection:
            report = proj.doctor_report(plan_roots, reference_context)
            messages = [str(message) for message in report["messages"]]
            projection_preview = [
                dict(row)
                for row in report.get("projection_drift", [])
                if isinstance(row, dict)
            ]
        else:
            messages = proj.doctor(plan_roots, reference_context)
        if archive_store is not None and hasattr(proj, "list_issues"):
            try:
                archive_report = inspect_plan_archive_health(
                    proj.list_issues(),
                    archive_store,
                    plan_roots=plan_roots,
                )
            except Exception as exc:  # noqa: BLE001 - doctor reports availability.
                archive_report = unavailable_plan_archive_report(
                    exc,
                    sidecar_root=archive_store.kind_root("plans"),
                    plan_roots=plan_roots,
                )
            messages = _extend_doctor_messages(
                messages,
                render_plan_archive_health_messages(archive_report),
            )
        try:
            from sase.bead.attachment_doctor import (
                inspect_attachment_health,
                render_attachment_health_messages,
            )

            attachment_report = inspect_attachment_health()
            messages = _extend_doctor_messages(
                messages,
                render_attachment_health_messages(attachment_report),
            )
        except Exception as exc:  # noqa: BLE001 - doctor reports availability.
            attachment_report = None
            messages = _extend_doctor_messages(
                messages,
                [f"WARNING: attachment doctor unavailable: {exc}"],
            )
        for line in _read_model_doctor_lines(proj, verify_cache=verify_cache):
            messages.append(line)
        for msg in messages:
            print(msg)
        preview = (
            plan_design_ref_repairs(
                proj.list_issues(),
                roots=plan_roots,
            )
            if fix_design_refs
            else None
        )

    if fix_projection:
        _repair_projection(
            projection_preview, plan_roots, reference_context, assume_yes
        )

    if fix_plan_archive:
        if archive_store is None:
            archive_report = unavailable_plan_archive_report(
                RuntimeError("active SDD store could not be resolved"),
                plan_roots=plan_roots,
            )
        assert archive_report is not None
        _repair_plan_archive(archive_report, archive_store, plan_roots, assume_yes)

    if fix_issue_prefix:
        _repair_issue_prefix(assume_yes)

    if fix_attachments:
        _repair_attachments(attachment_report, assume_yes)

    if preview is None:
        return
    _render_design_ref_repair_preview(preview)
    if not preview.repairs:
        print("No design references can be repaired safely.")
        return
    if not (assume_yes or _confirm_design_ref_repairs(len(preview.repairs))):
        print("Design reference repair cancelled; no changes applied.")
        return

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        current_preview = plan_design_ref_repairs(
            mutation.project.list_issues(),
            roots=plan_roots,
        )
        if current_preview != preview:
            print(
                "ERROR: bead design references changed after the preview; "
                "no changes applied.",
                file=sys.stderr,
            )
            return
        for repair in preview.repairs:
            mutation.project.update(
                repair.bead_id,
                design=repair.new_reference,
            )
        mutation.commit(
            "chore(beads): repair "
            f"{len(preview.repairs)} design reference"
            f"{'' if len(preview.repairs) == 1 else 's'}"
        )
    print(
        f"✓ Repaired {len(preview.repairs)} bead design reference"
        f"{'' if len(preview.repairs) == 1 else 's'}"
    )


def _read_model_doctor_lines(proj: object, *, verify_cache: bool) -> list[str]:
    """Return read-model status (and optional verify) lines for doctor."""
    from sase.core import bead_read_facade as rust_beads

    beads_dir = getattr(proj, "beads_dir", None)
    if beads_dir is None:
        return []
    lines = [_render_read_model_status(rust_beads.read_model_status(beads_dir))]
    if verify_cache:
        lines.extend(
            _render_read_model_verify(rust_beads.read_model_verify_cache(beads_dir))
        )
    return lines


def _render_read_model_status(status: dict[str, Any] | None) -> str:
    """Render one read-model cache health line for doctor output."""
    if status is None:
        return "Read model: unavailable with the installed core"
    location = status.get("location")
    if not isinstance(location, str) or not location:
        reason = status.get("reason") or "no cache location"
        return f"Read model: unavailable ({reason})"
    age = status.get("last_sweep_age_secs")
    age_text = f"{age}s ago" if isinstance(age, int) else "age unknown"
    if status.get("fresh"):
        freshness = "fresh"
    else:
        freshness = f"stale ({status.get('reason') or 'changed'})"
    line = (
        f"Read model: {location} "
        f"(generation {status.get('generation', 0)}, "
        f"{status.get('size_bytes', 0)} bytes, "
        f"{status.get('issues', 0)} issues, "
        f"last sweep {age_text}, {freshness}"
    )
    serve = status.get("serve_count")
    tail = status.get("tail_count")
    rebuild = status.get("rebuild_count")
    if isinstance(serve, int) and isinstance(tail, int) and isinstance(rebuild, int):
        line += f", outcomes serve={serve} tail={tail} rebuild={rebuild}"
        last_refresh = status.get("last_refresh") or ""
        last_reason = status.get("last_refresh_reason") or ""
        if last_refresh:
            line += f", last refresh: {last_refresh} ({last_reason})"
    return line + ")"


def _render_read_model_verify(report: dict[str, Any] | None) -> list[str]:
    """Render cache-vs-replay verify lines for doctor --verify-cache."""
    if report is None:
        return ["Read model verify: unavailable with the installed core"]
    if not report.get("compared", False):
        reason = report.get("reason") or "comparison did not run"
        return [f"Read model verify: not compared ({reason})"]
    if report.get("matched", False):
        return [
            "Read model verify: cache matches replay "
            f"({report.get('replay_issues', 0)} issues)"
        ]
    lines = [
        "Read model verify: DRIFT "
        f"({report.get('reason') or 'cache differs from replay'}; "
        f"replay={report.get('replay_issues', 0)} "
        f"cache={report.get('cache_issues', 0)})"
    ]
    differing = report.get("differing_ids")
    if isinstance(differing, list) and differing:
        lines.append(
            "Read model verify: differing ids: "
            f"{', '.join(str(item) for item in differing)}"
        )
    return lines


def _extend_doctor_messages(messages: list[str], extra: list[str]) -> list[str]:
    if not extra:
        return messages
    ok_message = "OK: no issues found"
    if messages == [ok_message]:
        messages = []
    messages.extend(extra)
    return messages


def _repair_plan_archive(
    preview: PlanArchiveDoctorReport,
    archive_store: Any,
    plan_roots: tuple[Path, ...],
    assume_yes: bool,
) -> None:
    for line in preview_plan_archive_repairs(preview):
        print(line)
    repair_count = len(preview.recoverable_findings)
    if not repair_count:
        print("No plan archives can be repaired on this machine.")
        return
    if not (assume_yes or _confirm_plan_archive_repair(repair_count)):
        print("Plan archive repair cancelled; no changes applied.")
        return

    with get_project() as proj:
        current = inspect_plan_archive_health(
            proj.list_issues(),
            archive_store,
            plan_roots=plan_roots,
        )
    if current != preview:
        print(
            "ERROR: plan archive findings changed after the preview; "
            "no changes applied.",
            file=sys.stderr,
        )
        return

    result = repair_plan_archive(
        preview,
        archive_store,
        primary_root=Path.cwd(),
    )
    if not result.repaired:
        print("No plan archive changes were needed.")
        return
    committed = " and committed" if result.committed else ""
    print(
        f"✓ Repaired {len(result.repaired)} plan archive"
        f"{'' if len(result.repaired) == 1 else 's'}{committed}"
    )


def _repair_projection(
    preview: list[dict[str, Any]],
    plan_roots: tuple[Path, ...],
    reference_context: ArtifactRefContext | None,
    assume_yes: bool,
) -> None:
    _render_projection_repair_preview(preview)
    if not preview:
        print("No projection drift to repair.")
        return
    refusal = _projection_repair_refusal(preview)
    if refusal is not None:
        print(
            f"ERROR: refusing projection repair: {refusal}",
            file=sys.stderr,
        )
        return
    if not (assume_yes or _confirm_projection_repair(len(preview))):
        print("Projection repair cancelled; no changes applied.")
        return

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        current_report = mutation.project.doctor_report(
            plan_roots,
            reference_context,
        )
        current_preview = [
            dict(row)
            for row in current_report.get("projection_drift", [])
            if isinstance(row, dict)
        ]
        if current_preview != preview:
            print(
                "ERROR: issues.jsonl projection drift changed after the "
                "preview; no changes applied.",
                file=sys.stderr,
            )
            return
        refusal = _projection_repair_refusal(current_preview)
        if refusal is not None:
            print(
                f"ERROR: refusing projection repair: {refusal}",
                file=sys.stderr,
            )
            return
        mutation.project.reproject_from_events()
        mutation.commit("chore(beads): reproject bead state from canonical events")
    print(
        f"✓ Reprojected {len(preview)} bead row"
        f"{'' if len(preview) == 1 else 's'} from canonical events"
    )


def _repair_issue_prefix(assume_yes: bool) -> None:
    from sase.bead.prefix_policy import (
        repair_stale_key_prefix,
        stale_key_prefix_report,
    )

    with get_project() as proj:
        report = stale_key_prefix_report(proj.beads_dir)
        beads_dir = proj.beads_dir

    if report is None:
        print("No issue prefix to repair.")
        return

    _render_issue_prefix_repair_preview(report)
    if not (assume_yes or _confirm_issue_prefix_repair(report)):
        print("Issue prefix repair cancelled; no changes applied.")
        return

    from sase.bead.sync import bead_store_write_lock

    with bead_store_write_lock(beads_dir) as already_locked:
        if stale_key_prefix_report(beads_dir) != report:
            print(
                "ERROR: bead issue prefix changed after the preview; "
                "no changes applied.",
                file=sys.stderr,
            )
            return
        stored, corrected = report
        repair_stale_key_prefix(beads_dir)
        auto_commit_bead_store(
            f"chore(beads): repair issue prefix {stored} -> {corrected}",
            push_after_commit=False,
            already_locked=already_locked,
        )
    stored, corrected = report
    print(f"✓ Repaired bead issue prefix: {stored} -> {corrected}")


def _render_issue_prefix_repair_preview(report: tuple[str, str]) -> None:
    stored, corrected = report
    print("Issue prefix repair preview:")
    print(f"  {stored} -> {corrected}")
    print(
        "Existing bead IDs keep the old prefix; only new top-level beads use "
        f"'{corrected}'."
    )


def _confirm_issue_prefix_repair(report: tuple[str, str]) -> bool:
    if not sys.stdin.isatty():
        return False
    stored, corrected = report
    try:
        answer = input(f"Reset issue prefix from '{stored}' to '{corrected}'? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _render_projection_repair_preview(
    preview: list[dict[str, Any]],
) -> None:
    print("Projection repair preview:")
    if not preview:
        print("  (no drift)")
        return
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in preview:
        for field in row.get("changed_fields", []):
            by_field[str(field)].append(row)
    for field in sorted(by_field):
        rows = by_field[field]
        print(f"  {field} ({len(rows)} row(s)):")
        for row in rows:
            current = row.get("current")
            reduced = row.get("reduced")
            old_value = (
                current.get(field) if isinstance(current, dict) else "<missing row>"
            )
            new_value = (
                reduced.get(field) if isinstance(reduced, dict) else "<missing row>"
            )
            print(
                f"    {row.get('issue_id')}: "
                f"{_render_projection_value(old_value)} -> "
                f"{_render_projection_value(new_value)}"
            )


def _projection_repair_refusal(
    preview: list[dict[str, Any]],
) -> str | None:
    # close_history is allowed because the first repair after the close-history
    # upgrade legitimately materializes archived records for beads whose close
    # reasons were destroyed by a reopen before sase-core started archiving them.
    allowed_fields = {"closed_at", "close_reason", "close_history", "updated_at"}
    for row in preview:
        issue_id = str(row.get("issue_id", "<unknown>"))
        current = row.get("current")
        reduced = row.get("reduced")
        if not isinstance(current, dict) or not isinstance(reduced, dict):
            return f"{issue_id} would change the issues.jsonl row set"
        fields = {str(field) for field in row.get("changed_fields", [])}
        unexpected = sorted(fields - allowed_fields)
        if unexpected:
            return f"{issue_id} changes unexpected field(s): {', '.join(unexpected)}"
        if current.get("status") != reduced.get("status"):
            return f"{issue_id} changes status"
        if "closed_at" in fields:
            reason = _closed_at_repair_refusal(
                current.get("closed_at"),
                reduced.get("closed_at"),
            )
            if reason is not None:
                return f"{issue_id} {reason}"
    return None


def _closed_at_repair_refusal(current: object, reduced: object) -> str | None:
    if not isinstance(current, str):
        return "adds a closed_at value where none was recorded"
    if reduced is None:
        return None
    if not isinstance(reduced, str):
        return "has an invalid reduced closed_at value"
    try:
        current_time = datetime.fromisoformat(current.replace("Z", "+00:00"))
        reduced_time = datetime.fromisoformat(reduced.replace("Z", "+00:00"))
    except ValueError:
        return "has an unparseable closed_at value"
    if reduced_time > current_time:
        return f"moves closed_at later ({current} -> {reduced})"
    return None


def _render_projection_value(value: object) -> str:
    if value == "<missing row>":
        return str(value)
    return json.dumps(value, sort_keys=True)


def _confirm_projection_repair(row_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Rewrite {row_count} stale projection row"
            f"{'' if row_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _repair_attachments(attachment_report: Any | None, assume_yes: bool) -> None:
    from sase.bead.attachment_doctor import (
        inspect_attachment_health,
        preview_attachment_repairs,
        repair_attachment_health,
    )

    report = attachment_report
    if report is None:
        try:
            report = inspect_attachment_health()
        except Exception as exc:  # noqa: BLE001 - doctor reports availability.
            print(f"Attachment repair unavailable: {exc}", file=sys.stderr)
            return
    for line in preview_attachment_repairs(report):
        print(line)
    if not any(
        [
            getattr(report, "orphans", ()),
            getattr(report, "corrupt", ()),
            getattr(report, "pending_upload", 0),
            getattr(report, "outbox_unreadable", False),
        ]
    ):
        print("No attachment repairs apply.")
        return
    if not (assume_yes or _confirm_attachment_repair()):
        print("Attachment repair cancelled; no changes applied.")
        return
    try:
        current = inspect_attachment_health()
    except Exception as exc:  # noqa: BLE001 - doctor reports availability.
        print(f"Attachment repair unavailable: {exc}", file=sys.stderr)
        return
    for result in repair_attachment_health(current):
        print(result)
    print("✓ Attachment repair complete")


def _confirm_attachment_repair() -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input("Apply attachment repairs? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _confirm_plan_archive_repair(repair_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Archive {repair_count} missing plan"
            f"{'' if repair_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _resolve_doctor_plan_archive_store(
    *,
    materialize: bool,
) -> Any | None:
    try:
        from sase.bead.cli_location import resolve_beads_location
        from sase.sdd.store import SddStore

        location = resolve_beads_location(
            require_existing=True,
            materialize=materialize,
        )
        if location is None:
            return None
        if location.store is not None:
            return location.store
        if location.storage == "in_tree":
            return SddStore(
                storage="in_tree",
                sdd_dir=location.root / "sdd",
                repo_root=location.root,
            )
        if location.storage == "local":
            return SddStore(
                storage="local",
                sdd_dir=location.root,
                repo_root=location.root,
            )
    except Exception:
        return None
    return None


def _resolve_doctor_plan_roots() -> tuple[Path, ...]:
    try:
        from sase.sdd.plan_refs import (
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )

        workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
        return resolve_plan_roots(workspace_dir, workspace_num)
    except Exception:
        return ()


def _resolve_doctor_reference_context() -> ArtifactRefContext | None:
    try:
        from sase.artifact_ref_context import artifact_ref_context
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution

        workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
        return artifact_ref_context(workspace_dir, workspace_num)
    except Exception:
        return None


def _render_design_ref_repair_preview(
    preview: DesignRefRepairPreview,
) -> None:
    print("Design reference repair preview:")
    if preview.repairs:
        for repair in preview.repairs:
            print(
                f"  {repair.bead_id}: {repair.old_reference} -> {repair.new_reference}"
            )
    else:
        print("  (no repairs)")
    print("Unrepaired design references:")
    if preview.unrepaired:
        for unrepaired in preview.unrepaired:
            print(
                f"  {unrepaired.bead_id}: {unrepaired.old_reference} "
                f"({unrepaired.reason})"
            )
    else:
        print("  (none)")


def _confirm_design_ref_repairs(repair_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Apply {repair_count} design reference repair"
            f"{'' if repair_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Source of truth:
  Version-controlled projects use this checkout's sdd/beads/ event store.
  issues.jsonl remains a generated compatibility projection.
  Normal reads do not merge numbered sibling workspaces or legacy stores.

Quick Start:
  sase bead init                                 Create sdd/beads/ in current directory
  Agents: use /sase_new_task before creating any task bead
  sase bead create -t "Follow-up" --type 'task(bug)' --size small \\
      -w "A second agent reproduced this failure" \\
      -f location=src/foo.py -f repro='fails on retry'
                                                  Create a standalone typed draft task
  sase bead +1 <task-id> -n "Independent repro"  Corroborate an existing task
  sase bead create -t "Fix bug" --type phase(<plan-id>) -w "Epic plan defines this phase"
  sase bead create -t "New feature" --type plan(sdd/plans/202605/feature.md) --tier plan -w "Planning the feature breakdown"
  sase bead create -t "Epic" --type plan(sdd/plans/202605/epic.md) --tier epic -w "Planning the epic breakdown"
  sase bead list                                 List open/claimed/ready/in-progress issues
  sase bead task-type                            List agent-creatable task types
  sase bead task-type show flake                 Inspect one type's fields and template
  sase bead list --format=json                   Machine-readable listing
  sase bead list --limit=5                       Limit printed issues
  sase bead list --status=open                   List open issues
  sase bead list --status=closed                 List newest 20 closed issues (-n 0 for all)
  sase bead list --tier=epic                     List epic plan beads
  sase bead list --type=task --since=1w --status=all
                                                  Task beads created in the last week
  sase bead ready                                Show unblocked ready task beads
  sase bead read <id> -r "<why>"                 Audited agent read with a reason
  sase bead show <id>                            View issue details (human viewing)
  sase bead show <id> --format=json              Machine-readable bead detail
  sase bead show <epic-id>..                     Show an epic plus its direct children
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead open <id>                            Reopen an issue
  sase bead snooze <id> -u 3d -r "why"           Defer a task until a wake time
  sase bead snooze <id> -u 3d -p 2               Also wake it at 2 more +1s
  sase bead snooze <id> --cancel                 Wake a snoozed task now
  sase bead epic-symbols [<id>]                  List Justfile --epic-symbol entries
  sase bead close <id> --note "verified"         Close with completion evidence
  sase bead attach <id> ./shot.png -n "trace"    Attach a file snapshot (bytes kept on every machine)
  Attachments get an automatic audience: clean workspace files go public, the rest stays
  private. Pass -K for secrets; never pass -W as an agent — offer publish via /sase_gate
  sase bead rm <id> [<id2> ...]                 Remove issues (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead dep list [<id>]                      Inspect dependency provenance
  sase bead dep tree [<id>]                      Follow dependency chains
  sase bead dep rm <issue> <depends-on> [...]    Remove dependency edges
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Stage bead state in git
  sase bead stats                                Project statistics
  sase bead doctor                               Health and reference checks
  sase bead doctor --fix-design-refs             Repair legacy plan links
  sase bead doctor --fix-issue-prefix            Reset a leaked ProjectSpec-key issue prefix
  sase bead doctor --fix-plan-archive            Archive recoverable missing plans
  sase bead doctor --fix-projection              Repair issues.jsonl drift
  sase bead doctor --fix-attachments             Repair attachment orphans and uploads
  sase bead doctor --verify-cache                Compare the read-model cache against replay
  sase bead work <target> [<target> ...]        Launch plan, epic, or task agents in order""")


def handle_bead_resolve_conflicts(args: argparse.Namespace) -> None:
    raise SystemExit(handle_resolve_conflicts_command())
