"""Change manifests, console summaries, and review reports for visual maintenance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from tests.ace.tui.visual._visual_capture_paths import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    atomic_write_text,
)
from tests.ace.tui.visual._visual_maintenance_lock import cache_root
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    KIND_CREATED,
    KIND_UPDATED,
    MANIFEST_FILENAME,
    STATUS_DRIFT,
    STATUS_FAILED,
    STATUS_REFUSED,
    ChangeManifest,
    ChangeRecord,
    GoldenBaseline,
    MaintenanceError,
    MaintenanceRequest,
    counts_from_changes,
)


REPORT_DIRNAME = "report"
LATEST_REPORT_FILENAME = "latest-report.json"

# Fallback repo root for locating the report renderer when the caller-provided
# root does not contain it. This module lives beside _visual_maintenance_run.py,
# so the same parents[4] layout applies.
_FALLBACK_REPO_ROOT = Path(__file__).resolve().parents[4]


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


def build_manifest(
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
        run_dir=posix_relative(run_dir, repo_root),
        capture_dir=posix_relative(capture_dir, repo_root),
        verify_dir=(
            None if verify_dir is None else posix_relative(verify_dir, repo_root)
        ),
        manifest_path=posix_relative(run_dir / MANIFEST_FILENAME, repo_root),
        journal_path=journal_relpath,
        logs=dict(logs),
        git_index_fingerprint=baseline.git_index_fingerprint,
    )


def failure_manifest(
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
    return build_manifest(
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


def write_manifest(repo_root: Path, run_dir: Path, manifest: ChangeManifest) -> None:
    atomic_write_text(
        run_dir / MANIFEST_FILENAME,
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
    )


def publish_manifest_and_report(
    repo_root: Path,
    run_dir: Path,
    manifest: ChangeManifest,
) -> None:
    """Write manifest, render its review report, and publish latest pointer."""
    write_manifest(repo_root, run_dir, manifest)
    try:
        metadata = render_manifest_report(repo_root, run_dir)
    except Exception as exc:
        raise MaintenanceError(
            "visual screenshot report generation failed; goldens were not changed: "
            f"{exc}"
        ) from exc
    manifest.extra["report"] = metadata
    write_manifest(repo_root, run_dir, manifest)
    write_latest_report_pointer(repo_root, manifest, metadata)


def try_publish_failure_manifest(
    repo_root: Path,
    run_dir: Path,
    manifest: ChangeManifest,
) -> None:
    try:
        publish_manifest_and_report(repo_root, run_dir, manifest)
    except MaintenanceError:
        write_manifest(repo_root, run_dir, manifest)


def render_manifest_report(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    tool = load_report_tool(repo_root)
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


def load_report_tool(repo_root: Path) -> Any:
    path = repo_root / "tools" / "render_visual_snapshot_failure_report"
    if not path.is_file():
        path = _FALLBACK_REPO_ROOT / "tools" / "render_visual_snapshot_failure_report"
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


def write_latest_report_pointer(
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


def posix_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
