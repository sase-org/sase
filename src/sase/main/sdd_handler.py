"""Handler for ``sase sdd`` subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .init_plan import InitAction, InitOperation, InitPlan


def handle_sdd_command(args: argparse.Namespace) -> None:
    subcommand = getattr(args, "sdd_subcommand", None)
    if subcommand == "init":
        _handle_init(args)
    elif subcommand == "validate":
        _handle_validate(args)
    elif subcommand == "links":
        _handle_links(args)
    elif subcommand == "list":
        _handle_list(args)
    elif subcommand == "repair-links":
        _handle_repair_links(args)
    else:
        print("Usage: sase sdd {init,validate,links,list,repair-links}")
        sys.exit(1)


def _handle_init(args: argparse.Namespace) -> None:
    sys.exit(run_sdd_init(args))


def run_sdd_init(args: argparse.Namespace) -> int:
    """Create or refresh SDD generated files and return an exit code."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="sdd",
                    label="SDD",
                    plan=plan_sdd_init,
                    run=run_sdd_init,
                ),
            ),
        )

    from sase.sdd.files import write_sdd_readme

    readme_path = write_sdd_readme(getattr(args, "path", None))
    print(readme_path)
    return 0


def plan_sdd_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for SDD generated files."""
    from sase.sdd.files import (
        expected_sdd_directory_map,
        expected_sdd_directory_readmes,
        expected_sdd_readme,
    )

    path = getattr(args, "path", None)
    actions: list[InitAction] = []
    expected_text_files = (
        expected_sdd_readme(path),
        *expected_sdd_directory_readmes(path),
    )
    for expected_file in expected_text_files:
        operation = _planned_text_operation(expected_file.path, expected_file.content)
        if operation is not None:
            actions.append(
                InitAction(
                    path=expected_file.path,
                    operation=operation,
                    detail=_sdd_detail_for_path(expected_file.path),
                )
            )

    expected_map = expected_sdd_directory_map(path)
    operation = _planned_bytes_operation(expected_map.path, expected_map.content)
    if operation is not None:
        actions.append(
            InitAction(
                path=expected_map.path,
                operation=operation,
                detail="directory map asset",
            )
        )

    return InitPlan(
        command="sdd",
        label="SDD",
        summary=_summarize_sdd_actions(actions),
        actions=tuple(actions),
    )


def _planned_text_operation(path: Path, expected_content: str) -> InitOperation | None:
    if not path.exists():
        return "create"
    try:
        return (
            None if path.read_text(encoding="utf-8") == expected_content else "update"
        )
    except OSError:
        return "update"
    except UnicodeDecodeError:
        return "update"


def _planned_bytes_operation(
    path: Path, expected_content: bytes
) -> InitOperation | None:
    if not path.exists():
        return "create"
    try:
        return None if path.read_bytes() == expected_content else "update"
    except OSError:
        return "update"


def _sdd_detail_for_path(path: Path) -> str:
    if path.name == "README.md" and path.parent.name == "sdd":
        return "top-level README"
    return "directory README"


def _summarize_sdd_actions(actions: list[InitAction]) -> str:
    if not actions:
        return "SDD README files and directory map are current"
    operations = {action.operation for action in actions}
    if operations == {"create"}:
        return "create SDD README files and directory map"
    if operations == {"update"}:
        return "update SDD README files and directory map"
    return "refresh SDD README files and directory map"


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


def _handle_repair_links(args: argparse.Namespace) -> None:
    from sase.sdd.links import repair_sdd_links, repair_to_json

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
