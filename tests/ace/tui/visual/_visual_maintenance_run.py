"""Orchestrate capture, comparison, verification, and golden application."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import sys
from typing import Any

from tests.ace.tui.visual._visual_capture import load_inventory
from tests.ace.tui.visual._visual_maintenance_apply import (
    apply_changes,
    recover_unfinished_journals,
)
from tests.ace.tui.visual._visual_maintenance_baseline import (
    capture_golden_baseline,
    recheck_baseline_or_raise,
)
from tests.ace.tui.visual._visual_maintenance_cli import parse_command
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_captures,
    preserve_expected_bytes,
)
from tests.ace.tui.visual._visual_maintenance_exec import (
    assert_pruning_safe,
    build_run_pytest_command as build_run_pytest_command,
    run_governed_visual_pytest as run_governed_visual_pytest,
    run_pytest,
    verify_changes,
)
from tests.ace.tui.visual._visual_maintenance_guards import (
    default_is_ci as _default_is_ci,
    preflight,
    refuse_ci_update,
    renderer_identity,
)
from tests.ace.tui.visual._visual_maintenance_lock import (
    cache_root,
    create_run_dir,
    exclusive_maintenance_lock,
    new_run_id,
    write_run_record,
)
from tests.ace.tui.visual._visual_maintenance_manifest import (
    build_manifest,
    failure_manifest,
    print_summary as print_summary,
    publish_manifest_and_report,
    try_publish_failure_manifest,
)
from tests.ace.tui.visual._visual_maintenance_salvage import (
    run_update as run_update,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    JOURNAL_FILENAME,
    KIND_CREATED,
    KIND_UPDATED,
    STATUS_APPLIED,
    STATUS_CLEAN,
    STATUS_DRIFT,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_REFUSED,
    ChangeManifest,
    GoldenBaseline,
    MaintenanceError,
    MaintenanceHooks,
    MaintenanceRequest,
    UsageError,
    has_actionable_changes,
)


__all__ = [
    "REPO_ROOT",
    "_default_is_ci",
    "build_run_pytest_command",
    "main",
    "print_summary",
    "run_governed_visual_pytest",
    "run_maintenance",
]


REPO_ROOT = Path(__file__).resolve().parents[4]


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path | None = None,
    hooks: MaintenanceHooks | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run screenshot maintenance. Return the process exit code."""
    env = os.environ if environ is None else environ
    root = repo_root if repo_root is not None else REPO_ROOT
    active_hooks = hooks or MaintenanceHooks()
    try:
        request = parse_command(argv, environ=env)
    except UsageError as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    try:
        return run_maintenance(
            request,
            repo_root=root,
            hooks=active_hooks,
            environ=env,
        )
    except UsageError as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    except MaintenanceError as error:
        print(error, file=sys.stderr)
        return int(getattr(error, "exit_code", EXIT_FAILURE) or EXIT_FAILURE)
    except KeyboardInterrupt:
        print("fix-tui-screenshots interrupted", file=sys.stderr)
        return EXIT_FAILURE


def run_maintenance(
    request: MaintenanceRequest,
    *,
    repo_root: Path,
    hooks: MaintenanceHooks,
    environ: Mapping[str, str],
) -> int:
    """Execute one locked maintenance run."""
    run_id = new_run_id()
    with exclusive_maintenance_lock(repo_root, run_id=run_id, hooks=hooks):
        recover_unfinished_journals(
            cache_root(repo_root),
            repo_root,
            allow_writes=not request.check,
        )
        run_dir = create_run_dir(repo_root, run_id)
        capture_dir = run_dir / "capture"
        capture_dir.mkdir(parents=True, exist_ok=True)
        baseline = capture_golden_baseline(repo_root)
        renderer = renderer_identity(hooks)
        try:
            refuse_ci_update(request, hooks=hooks, environ=environ)
            preflight(request, hooks=hooks)
        except UsageError as error:
            manifest = failure_manifest(
                request,
                repo_root=repo_root,
                run_id=run_id,
                run_dir=run_dir,
                capture_dir=capture_dir,
                verify_dir=None,
                baseline=baseline,
                renderer=renderer,
                child_exit_code=None,
                logs={},
                status=STATUS_REFUSED,
                errors=(str(error),),
            )
            try_publish_failure_manifest(repo_root, run_dir, manifest)
            print_summary(manifest)
            raise
        write_run_record(
            run_dir,
            {
                "run_id": run_id,
                "mode": "check" if request.check else "update",
                "requested_scope": request.scope,
                "scope_reasons": list(request.scope_reasons),
                "arguments": list(request.argv),
                "pytest_args": list(request.pytest_args),
                "dirty_before": list(baseline.dirty_paths),
                "ace_tree_hash": baseline.ace_tree_hash,
                "pager_tree_hash": baseline.pager_tree_hash,
                "renderer": renderer,
                "check": request.check,
            },
        )
        return _run_locked(
            request,
            repo_root=repo_root,
            hooks=hooks,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            baseline=baseline,
            renderer=renderer,
        )


def _run_locked(
    request: MaintenanceRequest,
    *,
    repo_root: Path,
    hooks: MaintenanceHooks,
    run_id: str,
    run_dir: Path,
    capture_dir: Path,
    baseline: GoldenBaseline,
    renderer: dict[str, Any],
) -> int:
    if not request.check:
        return run_update(
            request,
            repo_root=repo_root,
            hooks=hooks,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            baseline=baseline,
            renderer=renderer,
        )
    return _run_locked_check(
        request,
        repo_root=repo_root,
        hooks=hooks,
        run_id=run_id,
        run_dir=run_dir,
        capture_dir=capture_dir,
        baseline=baseline,
        renderer=renderer,
    )


def _run_locked_check(
    request: MaintenanceRequest,
    *,
    repo_root: Path,
    hooks: MaintenanceHooks,
    run_id: str,
    run_dir: Path,
    capture_dir: Path,
    baseline: GoldenBaseline,
    renderer: dict[str, Any],
) -> int:
    logs = {"capture": str((run_dir / "capture.log").relative_to(repo_root))}
    child_exit: int | None = None
    verify_dir: Path | None = None
    journal_relpath: str | None = None
    terminal_manifest: ChangeManifest | None = None
    try:
        child_exit = run_pytest(
            hooks,
            repo_root=repo_root,
            capture_dir=capture_dir,
            run_id=run_id,
            scope=request.scope,
            pytest_args=request.pytest_args,
            log_path=run_dir / "capture.log",
            workers=request.workers,
        )
        inventory_path = capture_dir / "inventory.json"
        if not inventory_path.is_file():
            raise MaintenanceError(
                "visual pytest finished without writing capture inventory.json; "
                f"child_exit_code={child_exit}"
            )
        inventory = load_inventory(inventory_path)
        if child_exit != 0:
            raise MaintenanceError(
                "visual pytest failed; candidates were retained but goldens "
                f"were not changed (child_exit_code={child_exit})"
            )
        if inventory.session_exitstatus != 0:
            raise MaintenanceError(
                "capture session exit status "
                f"{inventory.session_exitstatus} is not success"
            )
        if not inventory.executed_visual_node_ids and not inventory.captures:
            raise MaintenanceError(
                "visual pytest selection executed zero tests; refusing to "
                "treat an empty run as a screenshot inventory"
            )
        if request.scope == "full" and not inventory.full_inventory:
            reasons = ", ".join(inventory.reasons) or "incomplete evidence"
            raise MaintenanceError(
                "requested a full visual inventory but completeness evidence "
                f"is missing ({reasons})"
            )
        if not inventory.complete:
            reasons = ", ".join(inventory.reasons) or "incomplete evidence"
            raise MaintenanceError(f"capture inventory is incomplete ({reasons})")
        assert_pruning_safe(inventory, baseline)
        changes = classify_captures(
            inventory,
            baseline=baseline,
            repo_root=repo_root,
            capture_dir=capture_dir,
        )
        preserve_expected_bytes(run_dir, changes, repo_root)
        if not request.check and any(
            item.kind in {KIND_CREATED, KIND_UPDATED} for item in changes
        ):
            verify_dir = run_dir / "verify"
            verify_dir.mkdir(parents=True, exist_ok=True)
            logs["verify"] = str((run_dir / "verify.log").relative_to(repo_root))
            verify_changes(
                hooks,
                repo_root=repo_root,
                first=inventory,
                changes=changes,
                verify_dir=verify_dir,
                run_id=run_id,
                log_path=run_dir / "verify.log",
            )
        status = (
            STATUS_DRIFT
            if request.check and has_actionable_changes(changes)
            else STATUS_CLEAN
        )
        exit_code = EXIT_DRIFT if status == STATUS_DRIFT else EXIT_SUCCESS
        if not request.check and has_actionable_changes(changes):
            preapply_manifest = build_manifest(
                request,
                repo_root=repo_root,
                run_id=run_id,
                run_dir=run_dir,
                capture_dir=capture_dir,
                verify_dir=verify_dir,
                baseline=baseline,
                renderer=renderer,
                changes=changes,
                status=STATUS_DRIFT,
                exit_code=EXIT_SUCCESS,
                child_exit_code=child_exit,
                inventory_reasons=inventory.reasons,
                errors=inventory.errors,
                logs=logs,
                journal_relpath=None,
                extra={
                    "full_inventory": inventory.full_inventory,
                    "pruning_allowed": inventory.pruning_allowed,
                    "complete": inventory.complete,
                },
            )
            publish_manifest_and_report(repo_root, run_dir, preapply_manifest)
            recheck_baseline_or_raise(baseline, repo_root)
            try:
                apply_changes(
                    run_dir,
                    changes,
                    repo_root=repo_root,
                    capture_dir=capture_dir,
                    run_id=run_id,
                )
            except KeyboardInterrupt:
                terminal_manifest = build_manifest(
                    request,
                    repo_root=repo_root,
                    run_id=run_id,
                    run_dir=run_dir,
                    capture_dir=capture_dir,
                    verify_dir=verify_dir,
                    baseline=baseline,
                    renderer=renderer,
                    changes=changes,
                    status=STATUS_INTERRUPTED,
                    exit_code=EXIT_FAILURE,
                    child_exit_code=child_exit,
                    inventory_reasons=inventory.reasons,
                    errors=("interrupted during apply",),
                    logs=logs,
                    journal_relpath=None,
                    extra={
                        "full_inventory": inventory.full_inventory,
                        "pruning_allowed": inventory.pruning_allowed,
                        "complete": inventory.complete,
                    },
                )
                publish_manifest_and_report(repo_root, run_dir, terminal_manifest)
                print_summary(terminal_manifest)
                raise
            except MaintenanceError as error:
                terminal_manifest = build_manifest(
                    request,
                    repo_root=repo_root,
                    run_id=run_id,
                    run_dir=run_dir,
                    capture_dir=capture_dir,
                    verify_dir=verify_dir,
                    baseline=baseline,
                    renderer=renderer,
                    changes=changes,
                    status=STATUS_FAILED,
                    exit_code=EXIT_FAILURE,
                    child_exit_code=child_exit,
                    inventory_reasons=inventory.reasons,
                    errors=(str(error),),
                    logs=logs,
                    journal_relpath=None,
                    extra={
                        "full_inventory": inventory.full_inventory,
                        "pruning_allowed": inventory.pruning_allowed,
                        "complete": inventory.complete,
                    },
                )
                publish_manifest_and_report(repo_root, run_dir, terminal_manifest)
                print_summary(terminal_manifest)
                raise
            journal_relpath = str((run_dir / JOURNAL_FILENAME).relative_to(repo_root))
            status = STATUS_APPLIED
            exit_code = EXIT_SUCCESS
        manifest = build_manifest(
            request,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            verify_dir=verify_dir,
            baseline=baseline,
            renderer=renderer,
            changes=changes,
            status=status,
            exit_code=exit_code,
            child_exit_code=child_exit,
            inventory_reasons=inventory.reasons,
            errors=inventory.errors,
            logs=logs,
            journal_relpath=journal_relpath,
            extra={
                "full_inventory": inventory.full_inventory,
                "pruning_allowed": inventory.pruning_allowed,
                "complete": inventory.complete,
            },
        )
        publish_manifest_and_report(repo_root, run_dir, manifest)
        print_summary(manifest)
        return exit_code
    except KeyboardInterrupt:
        if terminal_manifest is not None:
            raise
        manifest = failure_manifest(
            request,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            verify_dir=verify_dir,
            baseline=baseline,
            renderer=renderer,
            child_exit_code=child_exit,
            logs=logs,
            status=STATUS_INTERRUPTED,
            errors=("interrupted",),
        )
        try_publish_failure_manifest(repo_root, run_dir, manifest)
        print_summary(manifest)
        raise
    except MaintenanceError as error:
        if terminal_manifest is not None:
            raise
        manifest = failure_manifest(
            request,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            verify_dir=verify_dir,
            baseline=baseline,
            renderer=renderer,
            child_exit_code=child_exit,
            logs=logs,
            status=STATUS_FAILED,
            errors=(str(error),),
        )
        try_publish_failure_manifest(repo_root, run_dir, manifest)
        print_summary(manifest)
        raise
