"""Bead doctor CLI command handler and diagnosis helpers.

The ``handle_bead_doctor`` orchestrator lives here with the diagnosis helpers
only it uses (read-model rendering, doctor context resolution, and design
reference repair). The repair operations it dispatches to live in
``cli_admin_repairs`` under public names.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_admin_repairs import (
    repair_attachments,
    repair_issue_prefix,
    repair_plan_archive,
    repair_projection,
)
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
    render_plan_archive_health_messages,
    unavailable_plan_archive_report,
)


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
        repair_projection(projection_preview, plan_roots, reference_context, assume_yes)

    if fix_plan_archive:
        if archive_store is None:
            archive_report = unavailable_plan_archive_report(
                RuntimeError("active SDD store could not be resolved"),
                plan_roots=plan_roots,
            )
        assert archive_report is not None
        repair_plan_archive(archive_report, archive_store, plan_roots, assume_yes)

    if fix_issue_prefix:
        repair_issue_prefix(assume_yes)

    if fix_attachments:
        repair_attachments(attachment_report, assume_yes)

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


__all__ = ["handle_bead_doctor"]
