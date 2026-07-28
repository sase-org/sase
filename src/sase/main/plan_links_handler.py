"""Handler for ``sase plan links`` commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, NoReturn


def handle_plan_links_command(args: argparse.Namespace) -> NoReturn:
    """Run the selected SDD prompt/plan link operation."""
    subcommand = getattr(args, "plan_links_subcommand", "list")
    if subcommand == "list":
        _handle_list(args)
    if subcommand == "refresh":
        _handle_refresh(args)
    if subcommand == "repair":
        _handle_repair(args)
    if subcommand == "validate":
        _handle_validate(args)

    print(f"Error: unknown plan links subcommand: {subcommand}", file=sys.stderr)
    sys.exit(2)


def _handle_list(args: argparse.Namespace) -> NoReturn:
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


def _handle_repair(args: argparse.Namespace) -> NoReturn:
    from sase.sdd.links import repair_sdd_links, repair_to_json

    if args.write and getattr(args, "path", None) is None:
        from sase.sdd.store import materialize_sdd_store

        materialize_sdd_store(Path.cwd(), _current_workspace_num())
    report = repair_sdd_links(args.path, write=args.write)
    print(json.dumps(repair_to_json(report), indent=2))
    has_errors = any(issue.severity == "error" for issue in report.issues)
    sys.exit(1 if has_errors else 0)


def _handle_refresh(args: argparse.Namespace) -> NoReturn:
    from sase.sdd.plan_links_refresh import (
        plan_links_refresh_to_json,
        refresh_plan_links,
    )

    store, primary_root, project = _refresh_context(args.path, write=args.write)
    report = refresh_plan_links(
        store,
        primary_root=primary_root,
        plan_ref=args.plan,
        write=args.write,
        project=project,
    )
    if args.json:
        print(json.dumps(plan_links_refresh_to_json(report), indent=2))
    else:
        _print_refresh(report)
    sys.exit(0 if report.ok else 1)


def _handle_validate(args: argparse.Namespace) -> NoReturn:
    from sase.sdd.links import validate_sdd_tree, validation_to_json

    validation = validate_sdd_tree(args.path, strict=args.strict)
    if args.json:
        print(json.dumps(validation_to_json(validation), indent=2))
    elif not args.quiet or not validation.ok:
        _print_validation(validation, show_warnings=args.show_warnings)
    sys.exit(0 if validation.ok else 1)


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


def _print_refresh(report: Any) -> None:
    verb = "would change" if not report.write else "changed"
    mode = "dry run" if not report.write else "write"
    print(
        f"Plan link refresh {mode}: {len(report.actions)} of "
        f"{report.scanned} plans {verb}"
    )
    for action in report.actions:
        migration = ", migrated parent" if action.parent_migrated else ""
        print(
            f"  {action.path}: {action.agents} agents, "
            f"{action.commits} commits{migration}"
        )
    if report.write and report.actions:
        status = "committed" if report.committed else "not committed"
        print(f"Plans-store batch: {status}")
    for issue in report.issues:
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(
            f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})",
            file=stream,
        )


def _refresh_context(
    path: str | None,
    *,
    write: bool,
) -> tuple[Any, Path, str | None]:
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import materialize_sdd_store, resolve_sdd_store

    primary_root, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
    project = None
    try:
        from sase.workflows.utils import get_project_from_workspace

        project = get_project_from_workspace()
    except Exception:
        pass

    current_store = (
        materialize_sdd_store(primary_root, workspace_num)
        if write and path is None
        else resolve_sdd_store(primary_root, workspace_num)
    )
    if path is None:
        return current_store, primary_root, project

    from sase.sdd._link_files import resolve_sdd_root
    from sase.sdd._paths import has_month_dirs

    resolved = resolve_sdd_root(path)
    plans_root = resolved if has_month_dirs(resolved) else resolved / "plans"
    if plans_root.resolve(strict=False) == current_store.kind_root("plans").resolve(
        strict=False
    ):
        return current_store, primary_root, project

    from sase.sdd.files import _git_toplevel
    from sase.sdd.store import SddStore

    repo_root = _git_toplevel(plans_root) or plans_root
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans_root,
        repo_root=repo_root,
    )
    return store, primary_root, project


def _current_workspace_num() -> int:
    try:
        from .utils import ensure_project_file_and_get_workspace_num

        _, workspace_num, _ = ensure_project_file_and_get_workspace_num(
            create_missing=False
        )
    except Exception:
        workspace_num = None
    return workspace_num or 1


__all__ = ["handle_plan_links_command"]
