"""Orchestrate capture, comparison, verification, and golden application."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from tests.ace.tui.visual._visual_capture import load_inventory
from tests.ace.tui.visual._visual_capture_paths import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    atomic_write_text,
)
from tests.ace.tui.visual._visual_maintenance_apply import (
    apply_changes,
    recover_unfinished_journals,
)
from tests.ace.tui.visual._visual_maintenance_baseline import (
    capture_golden_baseline,
    default_ace_root,
    default_pager_root,
    recheck_baseline_or_raise,
)
from tests.ace.tui.visual._visual_maintenance_cli import parse_command
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_captures,
    compare_verification_captures,
    preserve_expected_bytes,
)
from tests.ace.tui.visual._visual_maintenance_lock import (
    cache_root,
    create_run_dir,
    exclusive_maintenance_lock,
    new_run_id,
    write_run_record,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    JOURNAL_FILENAME,
    KIND_CREATED,
    KIND_UPDATED,
    MANIFEST_FILENAME,
    STATUS_APPLIED,
    STATUS_CLEAN,
    STATUS_DRIFT,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_REFUSED,
    ChangeManifest,
    ChangeRecord,
    GoldenBaseline,
    MaintenanceError,
    MaintenanceHooks,
    MaintenanceRequest,
    UsageError,
    counts_from_changes,
    has_actionable_changes,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_DIRNAME = "report"
LATEST_REPORT_FILENAME = "latest-report.json"


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
    with exclusive_maintenance_lock(repo_root, run_id=run_id):
        recover_unfinished_journals(
            cache_root(repo_root),
            repo_root,
            allow_writes=not request.check,
        )
        run_dir = create_run_dir(repo_root, run_id)
        capture_dir = run_dir / "capture"
        capture_dir.mkdir(parents=True, exist_ok=True)
        baseline = capture_golden_baseline(repo_root)
        renderer = _renderer_identity(hooks)
        try:
            _refuse_ci_update(request, hooks=hooks, environ=environ)
            _preflight(request, hooks=hooks)
        except UsageError as error:
            manifest = _failure_manifest(
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
            _try_publish_failure_manifest(repo_root, run_dir, manifest)
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
    logs = {"capture": str((run_dir / "capture.log").relative_to(repo_root))}
    child_exit: int | None = None
    verify_dir: Path | None = None
    journal_relpath: str | None = None
    terminal_manifest: ChangeManifest | None = None
    try:
        child_exit = _run_pytest(
            hooks,
            repo_root=repo_root,
            capture_dir=capture_dir,
            run_id=run_id,
            scope=request.scope,
            pytest_args=request.pytest_args,
            log_path=run_dir / "capture.log",
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
        _assert_pruning_safe(inventory, baseline)
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
            _verify_changes(
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
            preapply_manifest = _build_manifest(
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
            _publish_manifest_and_report(repo_root, run_dir, preapply_manifest)
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
                terminal_manifest = _build_manifest(
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
                _publish_manifest_and_report(repo_root, run_dir, terminal_manifest)
                print_summary(terminal_manifest)
                raise
            except MaintenanceError as error:
                terminal_manifest = _build_manifest(
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
                _publish_manifest_and_report(repo_root, run_dir, terminal_manifest)
                print_summary(terminal_manifest)
                raise
            journal_relpath = str((run_dir / JOURNAL_FILENAME).relative_to(repo_root))
            status = STATUS_APPLIED
            exit_code = EXIT_SUCCESS
        manifest = _build_manifest(
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
        _publish_manifest_and_report(repo_root, run_dir, manifest)
        print_summary(manifest)
        return exit_code
    except KeyboardInterrupt:
        if terminal_manifest is not None:
            raise
        manifest = _failure_manifest(
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
        _try_publish_failure_manifest(repo_root, run_dir, manifest)
        print_summary(manifest)
        raise
    except MaintenanceError as error:
        if terminal_manifest is not None:
            raise
        manifest = _failure_manifest(
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
        _try_publish_failure_manifest(repo_root, run_dir, manifest)
        print_summary(manifest)
        raise


def print_summary(manifest: ChangeManifest, *, stream: Any | None = None) -> None:
    """Print a compact console summary including the manifest path."""
    out = sys.stdout if stream is None else stream
    counts = manifest.counts
    print(
        f"fix-tui-screenshots: {manifest.mode} {manifest.status}",
        file=out,
    )
    print(f"scope: {manifest.requested_scope}", file=out)
    print(
        "counts: "
        f"created={counts.get(KIND_CREATED, 0)} "
        f"updated={counts.get(KIND_UPDATED, 0)} "
        f"unchanged={counts.get('unchanged', 0)} "
        f"stale={counts.get('stale', 0)}",
        file=out,
    )
    if manifest.dirty_before:
        print("dirty-before:", file=out)
        for path in manifest.dirty_before:
            print(f"  {path}", file=out)
    print(f"manifest: {manifest.manifest_path}", file=out)
    print(f"run-dir: {manifest.run_dir}", file=out)
    report = manifest.extra.get("report")
    if isinstance(report, Mapping):
        html = report.get("html")
        summary = report.get("summary")
        if isinstance(html, str):
            print(f"report: {html}", file=out)
        if isinstance(summary, str):
            print(f"report-summary: {summary}", file=out)
        groups = report.get("groups")
        if isinstance(groups, list) and groups:
            print("update-groups:", file=out)
            for group in groups[:5]:
                if not isinstance(group, Mapping):
                    continue
                group_id = group.get("id", "?")
                size = group.get("size", "?")
                representative = group.get("representative", "?")
                print(f"  {group_id}: {size} member(s), {representative}", file=out)
            if len(groups) > 5:
                print(f"  ... {len(groups) - 5} more group(s)", file=out)
    if manifest.mode == "check" and manifest.status == STATUS_DRIFT:
        print("run: just fix-tui-screenshots", file=out)
        if isinstance(report, Mapping) and isinstance(report.get("html"), str):
            print(f"inspect: {report['html']}", file=out)


def build_run_pytest_command(
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    ace_root: Path,
    pager_root: Path,
) -> list[str]:
    """Return the governed visual runner command for candidate capture."""
    command = [
        sys.executable,
        str(repo_root / "tools" / "run_pytest"),
        "visual",
        "--sase-visual-capture-dir",
        str(capture_dir),
        "--sase-visual-capture-run-id",
        run_id,
        "--sase-visual-capture-scope",
        scope,
        "--sase-visual-capture-ace-root",
        _posix_relative(ace_root, repo_root),
        "--sase-visual-capture-pager-root",
        _posix_relative(pager_root, repo_root),
        *pytest_args,
    ]
    return command


def run_governed_visual_pytest(
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    log_path: Path,
    ace_root: Path,
    pager_root: Path,
) -> int:
    """Invoke ``tools/run_pytest visual`` with candidate capture enabled."""
    command = build_run_pytest_command(
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
        scope=scope,
        pytest_args=pytest_args,
        ace_root=ace_root,
        pager_root=pager_root,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                log.write(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            return int(proc.wait())
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise


def _run_pytest(
    hooks: MaintenanceHooks,
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    log_path: Path,
) -> int:
    runner = hooks.run_pytest or run_governed_visual_pytest
    return runner(
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
        scope=scope,
        pytest_args=pytest_args,
        log_path=log_path,
        ace_root=default_ace_root(repo_root),
        pager_root=default_pager_root(repo_root),
    )


def _verify_changes(
    hooks: MaintenanceHooks,
    *,
    repo_root: Path,
    first: Any,
    changes: Sequence[ChangeRecord],
    verify_dir: Path,
    run_id: str,
    log_path: Path,
) -> None:
    node_ids = sorted(
        {
            change.node_id
            for change in changes
            if change.kind in {KIND_CREATED, KIND_UPDATED} and change.node_id
        }
    )
    if not node_ids:
        return
    child_exit = _run_pytest(
        hooks,
        repo_root=repo_root,
        capture_dir=verify_dir,
        run_id=f"{run_id}-verify",
        scope="targeted",
        pytest_args=tuple(node_ids),
        log_path=log_path,
    )
    inventory_path = verify_dir / "inventory.json"
    if child_exit != 0 or not inventory_path.is_file():
        raise MaintenanceError(
            "determinism verification pytest failed; goldens were not changed "
            f"(child_exit_code={child_exit})"
        )
    second = load_inventory(inventory_path)
    if not second.complete:
        reasons = ", ".join(second.reasons) or "incomplete"
        raise MaintenanceError(
            f"determinism verification inventory is incomplete ({reasons})"
        )
    mismatches = compare_verification_captures(first, second, node_ids)
    if mismatches:
        raise MaintenanceError(
            "determinism verification disagreed with the first capture: "
            + "; ".join(mismatches)
        )


def _assert_pruning_safe(inventory: Any, baseline: GoldenBaseline) -> None:
    """Refuse orphan deletion when a full run produced no captures for a root."""
    if not inventory.pruning_allowed:
        return
    if not inventory.captures:
        raise MaintenanceError(
            "full inventory produced no screenshot captures; refusing stale "
            "deletion so a failed capture plugin cannot wipe goldens"
        )
    captured_roots = {record.root_identity for record in inventory.captures}
    for identity in ("ace", "pager"):
        has_goldens = any(
            state.root_identity == identity for state in baseline.files.values()
        )
        if has_goldens and identity not in captured_roots:
            raise MaintenanceError(
                f"full inventory captured no {identity} screenshots; "
                "refusing stale deletion for that root"
            )


def _refuse_ci_update(
    request: MaintenanceRequest,
    *,
    hooks: MaintenanceHooks,
    environ: Mapping[str, str],
) -> None:
    if request.check:
        return
    is_ci = hooks.is_ci or _default_is_ci
    if is_ci(environ):
        raise UsageError(
            "update refused because CI or GITHUB_ACTIONS is set; re-run with --check"
        )


def _preflight(request: MaintenanceRequest, *, hooks: MaintenanceHooks) -> None:
    preflight = hooks.preflight
    if preflight is not None:
        preflight(not request.check)
        return
    _default_preflight(update=not request.check, platform_system=hooks.platform_system)


def _default_preflight(
    *,
    update: bool,
    platform_system: Any | None = None,
) -> None:
    from tests.ace.tui.visual.renderer_env import (
        RendererEnvironmentError,
        assert_renderer_environment,
    )

    try:
        if platform_system is None:
            assert_renderer_environment(update=update)
        else:
            assert_renderer_environment(
                update=update,
                platform_system=platform_system,
            )
    except RendererEnvironmentError as error:
        raise UsageError(str(error)) from error


def _default_is_ci(environ: Mapping[str, str]) -> bool:
    """Return whether *environ* is a real CI that must not write goldens.

    SASE agent workspaces export ``CI=true`` for pytest/tooling, so ``CI``
    alone is not enough when ``SASE_AGENT`` is set. Detached ``sase monitor``
    commands do not inherit ``SASE_AGENT*`` identity, but they do set
    ``SASE_MONITOR_ID``; treat that the same way. GitHub Actions still
    refuses because it sets ``GITHUB_ACTIONS``.
    """
    if _truthy(environ.get("GITHUB_ACTIONS")):
        return True
    if _truthy(environ.get("SASE_AGENT")) or _truthy(environ.get("SASE_MONITOR_ID")):
        return False
    return _truthy(environ.get("CI"))


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _renderer_identity(hooks: MaintenanceHooks) -> dict[str, Any]:
    if hooks.renderer_identity is not None:
        return hooks.renderer_identity()
    identity: dict[str, Any] = {
        "platform": f"{os.uname().sysname}-{os.uname().machine}"
        if hasattr(os, "uname")
        else "",
        "python_version": sys.version.split()[0],
    }
    try:
        from tests.ace.tui.visual.renderer_env import (
            load_renderer_environment_manifest,
        )

        manifest = load_renderer_environment_manifest()
        identity["packages"] = dict(manifest.packages)
        identity["fonts"] = dict(manifest.fonts)
    except Exception as error:
        identity["manifest_error"] = str(error)
    return identity


def _build_manifest(
    request: MaintenanceRequest,
    *,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    capture_dir: Path,
    verify_dir: Path | None,
    baseline: GoldenBaseline,
    renderer: dict[str, Any],
    changes: Sequence[ChangeRecord],
    status: str,
    exit_code: int,
    child_exit_code: int | None,
    inventory_reasons: Sequence[str],
    errors: Sequence[str],
    logs: Mapping[str, str],
    journal_relpath: str | None,
    extra: Mapping[str, Any],
) -> ChangeManifest:
    full_inventory = bool(extra.get("full_inventory", False))
    pruning_allowed = bool(extra.get("pruning_allowed", False))
    complete = bool(extra.get("complete", False))
    return ChangeManifest(
        run_id=run_id,
        mode="check" if request.check else "update",
        status=status,
        requested_scope=request.scope,
        scope_reasons=request.scope_reasons,
        full_inventory=full_inventory,
        pruning_allowed=pruning_allowed,
        complete=complete,
        exit_code=exit_code,
        child_exit_code=child_exit_code,
        counts=counts_from_changes(changes),
        dirty_before=baseline.dirty_paths,
        changes=tuple(changes),
        roots={
            "ace": {
                "path": DEFAULT_ACE_ROOT,
                "baseline_tree_hash": baseline.ace_tree_hash,
            },
            "pager": {
                "path": DEFAULT_PAGER_ROOT,
                "baseline_tree_hash": baseline.pager_tree_hash,
            },
        },
        renderer=renderer,
        arguments=request.argv,
        pytest_args=request.pytest_args,
        inventory_reasons=tuple(inventory_reasons),
        errors=tuple(errors),
        run_dir=_posix_relative(run_dir, repo_root),
        capture_dir=_posix_relative(capture_dir, repo_root),
        verify_dir=(
            None if verify_dir is None else _posix_relative(verify_dir, repo_root)
        ),
        manifest_path=_posix_relative(run_dir / MANIFEST_FILENAME, repo_root),
        journal_path=journal_relpath,
        logs=dict(logs),
        git_index_fingerprint=baseline.git_index_fingerprint,
    )


def _failure_manifest(
    request: MaintenanceRequest,
    *,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    capture_dir: Path,
    verify_dir: Path | None,
    baseline: GoldenBaseline,
    renderer: dict[str, Any],
    child_exit_code: int | None,
    logs: Mapping[str, str],
    status: str,
    errors: Sequence[str],
) -> ChangeManifest:
    return _build_manifest(
        request,
        repo_root=repo_root,
        run_id=run_id,
        run_dir=run_dir,
        capture_dir=capture_dir,
        verify_dir=verify_dir,
        baseline=baseline,
        renderer=renderer,
        changes=(),
        status=status if status != STATUS_FAILED else STATUS_FAILED,
        exit_code=EXIT_FAILURE if status != STATUS_REFUSED else EXIT_USAGE,
        child_exit_code=child_exit_code,
        inventory_reasons=(),
        errors=errors,
        logs=logs,
        journal_relpath=None,
        extra={"full_inventory": False, "pruning_allowed": False, "complete": False},
    )


def _write_manifest(repo_root: Path, run_dir: Path, manifest: ChangeManifest) -> None:
    atomic_write_text(
        run_dir / MANIFEST_FILENAME,
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
    )


def _publish_manifest_and_report(
    repo_root: Path,
    run_dir: Path,
    manifest: ChangeManifest,
) -> None:
    """Write manifest, render its review report, and publish latest pointer."""
    _write_manifest(repo_root, run_dir, manifest)
    try:
        metadata = _render_manifest_report(repo_root, run_dir)
    except Exception as exc:
        raise MaintenanceError(
            "visual screenshot report generation failed; goldens were not changed: "
            f"{exc}"
        ) from exc
    manifest.extra["report"] = metadata
    _write_manifest(repo_root, run_dir, manifest)
    _write_latest_report_pointer(repo_root, manifest, metadata)


def _try_publish_failure_manifest(
    repo_root: Path,
    run_dir: Path,
    manifest: ChangeManifest,
) -> None:
    try:
        _publish_manifest_and_report(repo_root, run_dir, manifest)
    except MaintenanceError:
        _write_manifest(repo_root, run_dir, manifest)


def _render_manifest_report(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    tool = _load_report_tool(repo_root)
    output_dir = run_dir / REPORT_DIRNAME
    context = tool.RenderContext(repo=None, sha=None, report_url=None)
    metadata = tool.write_outputs_from_manifest(
        run_dir / MANIFEST_FILENAME,
        output_dir=output_dir,
        context=context,
        repo_root=repo_root,
    )
    if not isinstance(metadata, dict):
        raise MaintenanceError("report renderer returned invalid metadata")
    return metadata


def _load_report_tool(repo_root: Path) -> Any:
    path = repo_root / "tools" / "render_visual_snapshot_failure_report"
    if not path.is_file():
        path = REPO_ROOT / "tools" / "render_visual_snapshot_failure_report"
    loader = importlib.machinery.SourceFileLoader(
        "_sase_visual_snapshot_report_tool",
        str(path),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise MaintenanceError(f"cannot load visual report tool: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _write_latest_report_pointer(
    repo_root: Path,
    manifest: ChangeManifest,
    metadata: Mapping[str, Any],
) -> None:
    pointer = {
        "run_id": manifest.run_id,
        "mode": manifest.mode,
        "status": manifest.status,
        "manifest": manifest.manifest_path,
        "report": metadata,
    }
    atomic_write_text(
        cache_root(repo_root) / LATEST_REPORT_FILENAME,
        json.dumps(pointer, indent=2, sort_keys=True) + "\n",
    )


def _posix_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
