"""Doctor check for duplicate raw ProjectSpec Patch blocks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.patch.duplicate_repair import (
    DuplicateBlockPreview,
    plan_duplicate_block_repairs,
)
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def project_spec_duplicate_check_specs(
    context: DoctorContext,
) -> tuple[CheckSpec, ...]:
    """Return ProjectSpec duplicate-block doctor specs."""
    return (
        CheckSpec(
            id="project.duplicate_patch_blocks",
            group="project",
            title="Duplicate Patch blocks",
            runner=lambda: _check_project_spec_duplicates(context),
        ),
    )


def _check_project_spec_duplicates(context: DoctorContext) -> DiagnosticCheck:
    projects_root = context.sase_home / "projects"
    if not projects_root.exists():
        return DiagnosticCheck(
            id="project.duplicate_patch_blocks",
            group="project",
            status="SKIP",
            title="Duplicate Patch blocks",
            summary="SASE projects directory is not present",
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": False,
                "project_count": 0,
                "duplicate_name_count": 0,
                "dropped_block_count": 0,
                "reclaimable_bytes": 0,
                "projects": [],
            },
        )

    try:
        previews = plan_duplicate_block_repairs(projects_root=projects_root)
    except OSError as exc:
        error = f"{type(exc).__name__}: {exc}"
        return DiagnosticCheck(
            id="project.duplicate_patch_blocks",
            group="project",
            status="ERROR",
            title="Duplicate Patch blocks",
            summary="SASE projects directory could not be scanned",
            details=(error,),
            next_steps=(f"Check permissions for {projects_root}.",),
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": True,
                "error": error,
            },
        )

    if not previews:
        return DiagnosticCheck(
            id="project.duplicate_patch_blocks",
            group="project",
            status="OK",
            title="Duplicate Patch blocks",
            summary="no duplicate Patch blocks found",
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": True,
                "project_count": 0,
                "duplicate_name_count": 0,
                "dropped_block_count": 0,
                "reclaimable_bytes": 0,
                "projects": [],
            },
        )

    duplicate_name_count = sum(_duplicate_name_count(preview) for preview in previews)
    dropped_block_count = sum(_dropped_block_count(preview) for preview in previews)
    reclaimable_bytes = sum(_reclaimable_bytes(preview) for preview in previews)
    return DiagnosticCheck(
        id="project.duplicate_patch_blocks",
        group="project",
        status="WARN",
        title="Duplicate Patch blocks",
        summary=(
            f"{len(previews)} project(s) have duplicate Patch blocks; "
            f"{reclaimable_bytes} bytes reclaimable"
        ),
        details=tuple(_detail_line(preview) for preview in previews[:_MAX_DETAIL_ROWS]),
        next_steps=(
            "Run `sase doctor -F` to preview and apply the ProjectSpec de-duplication repair.",
        ),
        data={
            "projects_root": str(projects_root),
            "projects_root_exists": True,
            "project_count": len(previews),
            "duplicate_name_count": duplicate_name_count,
            "dropped_block_count": dropped_block_count,
            "reclaimable_bytes": reclaimable_bytes,
            "projects": [_project_row(preview) for preview in previews],
            "details_truncated": len(previews) > _MAX_DETAIL_ROWS,
        },
    )


def _duplicate_name_count(preview: DuplicateBlockPreview) -> int:
    return len(preview.active_scan.duplicate_names) + len(
        preview.archive_scan.duplicate_names
    )


def _dropped_block_count(preview: DuplicateBlockPreview) -> int:
    return preview.active_scan.dropped_blocks + preview.archive_scan.dropped_blocks


def _reclaimable_bytes(preview: DuplicateBlockPreview) -> int:
    return (
        preview.active_scan.reclaimable_bytes + preview.archive_scan.reclaimable_bytes
    )


def _detail_line(preview: DuplicateBlockPreview) -> str:
    return (
        f"WARN: {preview.project_label}: {_duplicate_name_count(preview)} duplicate "
        f"name(s), {_reclaimable_bytes(preview)} bytes reclaimable"
    )


def _project_row(preview: DuplicateBlockPreview) -> dict[str, object]:
    return {
        "project": preview.project_key,
        "label": preview.project_label,
        "active_file": preview.active_file,
        "archive_file": preview.archive_file,
        "active_duplicate_name_count": len(preview.active_scan.duplicate_names),
        "archive_duplicate_name_count": len(preview.archive_scan.duplicate_names),
        "active_dropped_block_count": preview.active_scan.dropped_blocks,
        "archive_dropped_block_count": preview.archive_scan.dropped_blocks,
        "active_reclaimable_bytes": preview.active_scan.reclaimable_bytes,
        "archive_reclaimable_bytes": preview.archive_scan.reclaimable_bytes,
    }


__all__ = ["project_spec_duplicate_check_specs"]
