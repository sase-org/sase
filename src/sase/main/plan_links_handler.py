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
