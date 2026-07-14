"""Handler for ``sase sdd`` subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sase.project_management import ProjectManagementStatus, project_management_status

_UNMANAGED_SDD_MESSAGE = (
    "SDD initialization skipped: repository is not SASE-managed; set "
    "is_sase_managed: true in the target repository's sase.yml to enable it"
)


def handle_sdd_command(args: argparse.Namespace) -> None:
    subcommand = getattr(args, "sdd_subcommand", None)
    if subcommand == "init":
        _handle_init(args)
    elif subcommand == "migrate":
        _handle_migrate(args)
    elif subcommand == "validate":
        _handle_validate(args)
    elif subcommand == "links":
        _handle_links(args)
    elif subcommand == "list":
        _handle_list(args)
    elif subcommand == "path":
        _handle_path(args)
    elif subcommand == "repair-links":
        _handle_repair_links(args)
    else:
        print("Usage: sase sdd {init,links,list,migrate,path,repair-links,validate}")
        sys.exit(1)


def _handle_init(args: argparse.Namespace) -> None:
    from .repo_init_handler import run_repo_init

    # Retain ``sase sdd init`` for the Phase 3 compatibility window while the
    # implementation and onboarding registry move to ``sase repo init``.
    sys.exit(run_repo_init(args))


def _handle_migrate(args: argparse.Namespace) -> None:
    from sase.sdd.migrate import (
        apply_split_sdd_migration,
        plan_split_sdd_migration,
        render_split_sdd_migration_diff,
    )
    from sase.sdd.store import SddMaterializationError

    project_root, management = _sdd_project_management(getattr(args, "path", None))
    if management.error is not None:
        print(f"error: {management.error}", file=sys.stderr)
        sys.exit(1)
    if not management.is_sase_managed:
        print(_UNMANAGED_SDD_MESSAGE, file=sys.stderr)
        sys.exit(1)
    try:
        plan = plan_split_sdd_migration(project_root, 1)
        if getattr(args, "diff", False):
            rendered = render_split_sdd_migration_diff(plan)
            if rendered:
                print(rendered)
        if getattr(args, "check", False):
            if plan.has_changes:
                print(
                    f"SDD split migration required: {len(plan.actions)} files; "
                    f"legacy clone {plan.legacy_root}"
                )
                sys.exit(1)
            print("SDD split migration is current")
            sys.exit(0)
        applied = apply_split_sdd_migration(project_root, 1)
    except SddMaterializationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    if applied.legacy_root is None:
        print("SDD split migration is current")
    else:
        print(
            f"Migrated {len(applied.actions)} files and retired {applied.legacy_root}"
        )
    sys.exit(0)


def _sdd_project_management(
    path: str | Path | None,
) -> tuple[Path, ProjectManagementStatus]:
    from .sdd_init_config import resolve_sdd_init_config_path

    config_path = resolve_sdd_init_config_path(path)
    return config_path.parent, project_management_status(config_path)


def _handle_validate(args: argparse.Namespace) -> None:
    from sase.sdd.links import validate_sdd_tree, validation_to_json

    validation = validate_sdd_tree(args.path, strict=args.strict)
    if args.json:
        print(json.dumps(validation_to_json(validation), indent=2))
    elif not args.quiet or not validation.ok:
        _print_validation(validation, show_warnings=args.show_warnings)
    sys.exit(0 if validation.ok else 1)


def _handle_links(args: argparse.Namespace) -> None:
    from sase.sdd.links import collect_sdd_links, resolve_sdd_root

    root = resolve_sdd_root(args.path)
    if not root.is_dir():
        print(f"SDD path does not exist or is not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    rows = collect_sdd_links(root)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            target = row["target"] or "-"
            status = "ok" if row["bidirectional"] else "broken"
            print(f"{row['path']} -> {target} [{status}]")
    sys.exit(0)


def _handle_list(args: argparse.Namespace) -> None:
    from sase.sdd.links import files_to_json, list_sdd_files, resolve_sdd_root

    root = resolve_sdd_root(getattr(args, "path", None))
    if not root.is_dir():
        print(f"SDD path does not exist or is not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    files = list_sdd_files(root, kind=args.kind)
    if args.json:
        print(json.dumps(files_to_json(files), indent=2))
    else:
        for file in files:
            print(f"{file.kind}\t{file.relpath}")
    sys.exit(0)


def _handle_path(args: argparse.Namespace) -> None:
    from sase.sdd.store import (
        ensure_sdd_kind_clone,
        resolve_sdd_dir,
        resolve_sdd_kind_dir,
    )

    workspace_dir = Path.cwd()
    workspace_num = _current_workspace_num()
    kind = getattr(args, "kind", None)
    resolved_kind = kind or "plans"
    if getattr(args, "ensure", False):
        ensure_sdd_kind_clone(workspace_dir, workspace_num, resolved_kind, strict=True)
    root = resolve_sdd_dir(workspace_dir, workspace_num)
    print(
        root
        if kind is None
        else resolve_sdd_kind_dir(workspace_dir, workspace_num, kind)
    )
    sys.exit(0)


def _current_workspace_num() -> int:
    try:
        from .utils import ensure_project_file_and_get_workspace_num

        _, workspace_num, _ = ensure_project_file_and_get_workspace_num(
            create_missing=False
        )
    except Exception:
        workspace_num = None
    return workspace_num or 1


def _handle_repair_links(args: argparse.Namespace) -> None:
    from sase.sdd.links import repair_sdd_links, repair_to_json

    if args.write and getattr(args, "path", None) is None:
        from sase.sdd.store import materialize_sdd_store

        materialize_sdd_store(Path.cwd(), _current_workspace_num())
    report = repair_sdd_links(args.path, write=args.write)
    print(json.dumps(repair_to_json(report), indent=2))
    has_errors = any(issue.severity == "error" for issue in report.issues)
    sys.exit(1 if has_errors else 0)


def _print_validation(validation: Any, *, show_warnings: bool) -> None:
    warning_count = len(validation.warnings)
    hint = (
        " (use --show-warnings to display)"
        if warning_count and not show_warnings
        else ""
    )
    if validation.ok:
        print(
            f"SDD validation passed: {len(validation.files)} files, "
            f"{warning_count} warnings{hint}"
        )
    else:
        print(
            f"SDD validation failed: {len(validation.errors)} errors, "
            f"{warning_count} warnings{hint}"
        )
    for issue in validation.issues:
        if issue.severity == "warning" and not show_warnings:
            continue
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(
            f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})",
            file=stream,
        )
