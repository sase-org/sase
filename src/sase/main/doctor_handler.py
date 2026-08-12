"""Handler for the ``sase doctor`` top-level command."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sase.ace.patch.duplicate_repair import (
    DuplicateBlockPreview,
    DuplicateBlockRepairResult,
    apply_duplicate_block_repairs,
    plan_duplicate_block_repairs,
)
from sase.diagnostics import (
    UnknownCheckSelection,
    diagnostic_report_to_json,
    render_diagnostic_report,
)
from sase.doctor.runner import build_doctor_registry, default_doctor_context, run_doctor


def handle_doctor_command(args: argparse.Namespace) -> int:
    """Run or list top-level SASE doctor checks."""
    selections = tuple(getattr(args, "check", ()) or ())
    context = default_doctor_context(
        project=getattr(args, "project", None),
        verbose=bool(getattr(args, "verbose", False)),
    )
    registry = build_doctor_registry(context)

    if getattr(args, "list_checks", False):
        return _handle_list_checks(args, registry, selections)

    try:
        report = run_doctor(
            context=context,
            registry=registry,
            selections=selections,
            deep=bool(getattr(args, "deep", False)),
            strict=bool(getattr(args, "strict", False)),
        )
    except UnknownCheckSelection as exc:
        # A selection can be registered but deep-only; `-L` lists those, so
        # calling them "unknown" would be wrong. Point at -D/--deep instead.
        deep_only = _deep_only_selections(registry, exc.selections)
        unknown = [item for item in exc.selections if item not in set(deep_only)]
        if unknown:
            print(f"error: {UnknownCheckSelection(unknown)}", file=sys.stderr)
        if deep_only:
            joined = ", ".join(deep_only)
            print(
                f"error: {joined} selects deep checks only; "
                "rerun with -D/--deep to include them",
                file=sys.stderr,
            )
            return 2
        return 2

    if getattr(args, "json", False):
        print(diagnostic_report_to_json(report))
    else:
        from sase.project_display_names import load_project_display_snapshot

        render_diagnostic_report(
            report,
            verbose=bool(getattr(args, "verbose", False)),
            project_display_snapshot=load_project_display_snapshot(),
        )

    exit_code = report.exit_code()
    if getattr(args, "fix_duplicate_blocks", False):
        _handle_duplicate_block_repairs(
            context,
            assume_yes=bool(getattr(args, "yes", False)),
        )
    return exit_code


def _deep_only_selections(
    registry: Any,
    selections: tuple[str, ...],
) -> list[str]:
    """Return selections that resolve to deep-only check ids or groups."""
    deep_specs = registry.list_deep_checks()
    default_specs = registry.list_default_checks()
    deep_names = {spec.id for spec in deep_specs} | {spec.group for spec in deep_specs}
    default_names = {spec.id for spec in default_specs} | {
        spec.group for spec in default_specs
    }
    return [item for item in selections if item in deep_names - default_names]


def _handle_list_checks(
    args: argparse.Namespace,
    registry: Any,
    selections: tuple[str, ...],
) -> int:
    try:
        specs = (
            registry.select(selections, include_deep=True)
            if selections
            else registry.list_checks(include_deep=True)
        )
    except UnknownCheckSelection as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows = [
        {
            "id": spec.id,
            "group": spec.group,
            "title": spec.title,
            "deep": spec.deep,
        }
        for spec in specs
    ]
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "doctor",
                    "checks": rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for row in rows:
            mode = "deep" if row["deep"] else "default"
            print(f"{row['id']}\t{row['group']}\t{mode}\t{row['title']}")
    return 0


def _handle_duplicate_block_repairs(context: Any, *, assume_yes: bool) -> None:
    try:
        previews = plan_duplicate_block_repairs(
            projects_root=context.sase_home / "projects"
        )
    except OSError as exc:
        print(
            f"ProjectSpec de-duplication preview failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return

    if not previews:
        print("ProjectSpec de-duplication: nothing to repair.")
        return

    _render_duplicate_block_repair_preview(previews)
    if not (
        assume_yes
        or _confirm_duplicate_block_repairs(
            sum(_preview_dropped_blocks(preview) for preview in previews)
        )
    ):
        print("ProjectSpec de-duplication cancelled; no changes applied.")
        return

    results = apply_duplicate_block_repairs(previews)
    _render_duplicate_block_repair_results(results)


def _render_duplicate_block_repair_preview(
    previews: tuple[DuplicateBlockPreview, ...],
) -> None:
    print("ProjectSpec de-duplication preview:")
    for preview in previews:
        print(
            f"  {preview.project_label}: "
            f"{_preview_duplicate_names(preview)} duplicate name(s), "
            f"{_preview_dropped_blocks(preview)} block(s), "
            f"{_preview_reclaimable_bytes(preview)} bytes reclaimable"
        )
        if preview.active_scan.dropped_blocks:
            print(
                f"    active: {preview.active_scan.dropped_blocks} block(s), "
                f"{preview.active_scan.reclaimable_bytes} bytes"
            )
        if preview.archive_scan.dropped_blocks:
            print(
                f"    archive: {preview.archive_scan.dropped_blocks} block(s), "
                f"{preview.archive_scan.reclaimable_bytes} bytes"
            )


def _confirm_duplicate_block_repairs(dropped_blocks: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Apply ProjectSpec de-duplication and drop {dropped_blocks} block"
            f"{'' if dropped_blocks == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _render_duplicate_block_repair_results(
    results: tuple[DuplicateBlockRepairResult, ...],
) -> None:
    print("ProjectSpec de-duplication results:")
    total_blocks = 0
    total_bytes = 0
    failures = 0
    for result in results:
        if result.error:
            failures += 1
            print(f"  ERROR: {result.project_label}: {result.error}")
            continue
        for label, file_result in (
            ("active", result.active_result),
            ("archive", result.archive_result),
        ):
            if file_result is None or file_result.dropped_blocks == 0:
                continue
            total_blocks += file_result.dropped_blocks
            total_bytes += file_result.reclaimable_bytes
            print(
                f"  {result.project_label} {label}: dropped "
                f"{file_result.dropped_blocks} block(s), reclaimed "
                f"{file_result.reclaimable_bytes} bytes"
            )
    print(
        f"Total: dropped {total_blocks} block(s), reclaimed {total_bytes} bytes"
        + (f"; {failures} project(s) failed" if failures else "")
    )
    print("Rerun `sase doctor -C project.duplicate_patch_blocks` to confirm.")


def _preview_duplicate_names(preview: DuplicateBlockPreview) -> int:
    return len(preview.active_scan.duplicate_names) + len(
        preview.archive_scan.duplicate_names
    )


def _preview_dropped_blocks(preview: DuplicateBlockPreview) -> int:
    return preview.active_scan.dropped_blocks + preview.archive_scan.dropped_blocks


def _preview_reclaimable_bytes(preview: DuplicateBlockPreview) -> int:
    return (
        preview.active_scan.reclaimable_bytes + preview.archive_scan.reclaimable_bytes
    )


__all__ = ["handle_doctor_command"]
