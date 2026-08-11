"""Maintenance command handlers for ``sase patch``."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from sase.ace.patch import Patch
from sase.main.patch_common import command_prefix, file_location
from sase.project_display_names import humanize_cl_name


def resolve_set_origin_patch(
    name: str,
    project_file: str | None,
    args: argparse.Namespace,
    *,
    find_all_patches_fn: Callable[[], list[Patch]],
) -> Patch | None:
    """Resolve the named Patch, scoped to a project file when given."""

    if project_file:
        from sase.ace.patch import parse_project_file

        resolved_project_file = os.path.expanduser(project_file)
        if not os.path.isfile(resolved_project_file):
            print(
                f"[{command_prefix(args, 'set-origin')}] project file not found: "
                f"{resolved_project_file}",
                file=sys.stderr,
            )
            return None
        patches = parse_project_file(resolved_project_file)
    else:
        patches = find_all_patches_fn()

    matches = [patch for patch in patches if patch.name == name]
    if not matches:
        print(
            f"[{command_prefix(args, 'set-origin')}] Patch not found: {name}",
            file=sys.stderr,
        )
        return None
    if len(matches) > 1:
        print(
            f"[{command_prefix(args, 'set-origin')}] multiple Patches are named "
            f"{name}:",
            file=sys.stderr,
        )
        for patch in matches:
            print(f"  {file_location(patch)}", file=sys.stderr)
        return None
    return matches[0]


def handle_set_origin(
    args: argparse.Namespace,
    *,
    resolve_set_origin_patch_fn: Callable[
        [str, str | None, argparse.Namespace], Patch | None
    ],
) -> int:
    """Handle ``sase patch set-origin``."""
    from sase.status_state_machine import update_patch_pr_origin_atomic

    patch = resolve_set_origin_patch_fn(
        args.name,
        args.project_file,
        args,
    )
    if patch is None:
        return 1

    update_patch_pr_origin_atomic(patch.file_path, patch.name, args.origin)
    print(f"PR_ORIGIN set to {args.origin} for {humanize_cl_name(patch.name)}")
    return 0


def handle_migrate_extension(args: argparse.Namespace) -> int:
    """Run the ``.gp`` -> ``.sase`` migration helper."""
    from sase.ace.patch.project_spec_migration import migrate_all_projects

    projects_dir = Path(args.projects_dir).expanduser() if args.projects_dir else None
    report = migrate_all_projects(projects_dir, force=bool(args.force))

    for legacy, canonical in report.migrated:
        print(f"renamed {legacy} -> {canonical}")
    for legacy in report.skipped_identical:
        print(f"skipped (identical canonical sibling): {legacy}")
    for legacy, reason in report.conflicts:
        print(f"conflict: {legacy}: {reason}", file=sys.stderr)

    print(
        f"migrated={report.migrated_count} "
        f"skipped={report.skipped_count} "
        f"conflicts={report.conflict_count}"
    )
    return 0 if report.conflict_count == 0 else 1


__all__ = [
    "handle_migrate_extension",
    "handle_set_origin",
    "resolve_set_origin_patch",
]
