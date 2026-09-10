"""Artifact-link aggregate and primary-sidecar dirt checks for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.sdd._artifact_link_files import is_canonical_artifact_link_index_location
from sase.sdd._artifact_link_cutover_state import (
    ArtifactLinkCutoverMarker,
    inspect_artifact_link_cutover_markers,
)
from sase.sdd._artifact_link_store_support import is_projected_row
from sase.sdd.artifact_link_import_indexes import (
    artifact_link_legacy_links_tree_identity,
)
from sase.sdd.artifact_link_drift import (
    build_artifact_link_index_drift,
    format_artifact_link_index_drift,
)
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    artifact_link_aggregate_path,
    resolve_artifact_link_project_key,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR
from sase.sdd.store import document_sidecar_roles

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext
    from sase.sdd.store import SddStore

_CHECK_ID = "project.artifact_links_aggregate"
_CUTOVER_CHECK_ID = "project.artifact_link_cutover"
_CUTOVER_TITLE = "Artifact link cutover marker"
_DIRT_CHECK_ID = "project.primary_sidecar_link_dirt"
_DIRT_TITLE = "Primary sidecar link dirt"
_MAX_DETAIL_ROWS = 10
_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class PrimarySidecarLinkDirt:
    """One uncommitted ``links/`` path in a primary-nested sidecar clone."""

    role: str
    clone: Path
    path: str
    xy: str
    restorable: bool


@dataclass(frozen=True)
class PrimarySidecarLinkDirtRepairResult:
    """Outcome of restoring stranded link-index deletions in one clone."""

    role: str
    clone: Path
    restored: tuple[str, ...]
    error: str | None = None


def artifact_links_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return artifact-link aggregate and primary-sidecar dirt check specs."""

    return (
        CheckSpec(
            id=_CHECK_ID,
            group="project",
            title="Artifact link aggregate",
            runner=lambda: _check_artifact_links_aggregate(context),
        ),
        CheckSpec(
            id=_DIRT_CHECK_ID,
            group="project",
            title=_DIRT_TITLE,
            runner=lambda: _check_primary_sidecar_link_dirt(context),
        ),
        CheckSpec(
            id=_CUTOVER_CHECK_ID,
            group="project",
            title=_CUTOVER_TITLE,
            runner=lambda: _check_artifact_link_cutover(context),
        ),
    )


def _check_artifact_links_aggregate(context: DoctorContext) -> DiagnosticCheck:
    """Rebuild-compare the project aggregate against sidecar ``links/`` JSON."""

    store = _resolve_store(context)
    if store is None:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="SKIP",
            title="Artifact link aggregate",
            summary="no SDD store found in this checkout",
            data={"stale": False},
        )

    try:
        project_key = _project_key(context)
    except Exception as exc:  # noqa: BLE001 - make config failures actionable
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="ERROR",
            title="Artifact link aggregate",
            summary="could not resolve a canonical project key for artifact links",
            next_steps=str(exc),
            data={"stale": False, "error": str(exc)},
        )
    if not project_key:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="ERROR",
            title="Artifact link aggregate",
            summary="could not resolve a canonical project key for artifact links",
            next_steps=(
                "Check the workspace marker, ProjectSpec key, PROJECT_NAME, "
                "aliases, and provider slug for this checkout."
            ),
            data={"stale": False},
        )

    adapter = ArtifactLinkStore.from_sdd_store(store, project_key)
    on_disk = adapter.load_aggregate()
    expected = adapter.preview_aggregate()
    drift = build_artifact_link_index_drift(
        expected_rows=expected.get("rows", []),
        indexed_rows=on_disk.get("rows", []),
    )
    stale = drift.has_drift
    missing = not artifact_link_aggregate_path(project_key).is_file()
    expected_count = len(expected["rows"])
    projected_count = sum(1 for row in expected["rows"] if is_projected_row(row))
    if missing and expected_count == 0:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="OK",
            title="Artifact link aggregate",
            summary="no artifact link rows to index",
            data={"stale": False, "rows": 0},
        )
    if missing or stale:
        status: CheckStatus = "ERROR"
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status=status,
            title="Artifact link aggregate",
            summary=(
                "artifact-links aggregate is missing or stale versus durable links"
            ),
            next_steps=(
                "Rebuild ~/.sase/projects/<key>/artifact-links.json "
                "from durable store rows and projection rules; "
                f"{format_artifact_link_index_drift(drift)}.",
            ),
            data={
                "stale": True,
                "missing": missing,
                "rows": expected_count,
                "projected_rows": projected_count,
                "missing_rows": drift.missing.total,
                "extra_rows": drift.extra.total,
                "missing_by_relation": dict(drift.missing.by_relation),
                "extra_by_relation": dict(drift.extra.by_relation),
            },
        )
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="OK",
        title="Artifact link aggregate",
        summary=f"{expected_count} artifact link row(s) indexed",
        data={
            "stale": False,
            "rows": expected_count,
            "projected_rows": projected_count,
        },
    )


def _project_key(context: DoctorContext) -> str | None:
    return resolve_artifact_link_project_key(context.cwd, fallback=context.project)


def _resolve_store(context: DoctorContext) -> SddStore | None:
    try:
        from sase.sdd.checkout_anchor import resolve_checkout_anchor
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store

        anchor = resolve_checkout_anchor(context.cwd)
        primary_root, workspace_num = workspace_context_for_plan_resolution(
            anchor.primary_root
        )
        return resolve_sdd_store(primary_root, workspace_num)
    except Exception:  # noqa: BLE001 - a doctor check never breaks the report.
        return None


def _check_primary_sidecar_link_dirt(context: DoctorContext) -> DiagnosticCheck:
    """Error when a primary-nested sidecar clone has uncommitted ``links/`` dirt."""

    resolved = _resolve_primary_sidecar_store(context)
    if resolved is None:
        return DiagnosticCheck(
            id=_DIRT_CHECK_ID,
            group="project",
            status="SKIP",
            title=_DIRT_TITLE,
            summary="no primary sidecar store found in this checkout",
            data={"entries": ()},
        )

    primary, store = resolved
    dirt = _collect_primary_sidecar_link_dirt(primary, store)
    if not dirt:
        return DiagnosticCheck(
            id=_DIRT_CHECK_ID,
            group="project",
            status="OK",
            title=_DIRT_TITLE,
            summary="primary-nested sidecar clones have a clean links/ tree",
            data={"entries": (), "dirty_clones": 0, "restorable_deletions": 0},
        )

    clones = tuple(dict.fromkeys(entry.clone for entry in dirt))
    restorable = tuple(entry for entry in dirt if entry.restorable)
    details = tuple(_dirt_detail(entry) for entry in dirt[:_MAX_DETAIL_ROWS])
    return DiagnosticCheck(
        id=_DIRT_CHECK_ID,
        group="project",
        status="ERROR",
        title=_DIRT_TITLE,
        summary=(
            f"{len(clones)} primary sidecar clone(s) have uncommitted links/ "
            "dirt that blocks auto-sync"
        ),
        details=details,
        next_steps=_dirt_next_steps(restorable),
        data={
            "dirty_clones": len(clones),
            "restorable_deletions": len(restorable),
            "entries": tuple(_dirt_data(entry) for entry in dirt),
        },
    )


def _check_artifact_link_cutover(context: DoctorContext) -> DiagnosticCheck:
    """Validate artifact-link event-store cutover markers."""

    store = _resolve_store(context)
    if store is None:
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="SKIP",
            title=_CUTOVER_TITLE,
            summary="no SDD store found in this checkout",
            data={"state": "unknown"},
        )
    try:
        project_key = _project_key(context)
    except Exception as exc:  # noqa: BLE001 - doctor should report config failures.
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="ERROR",
            title=_CUTOVER_TITLE,
            summary="could not resolve a canonical project key for artifact links",
            next_steps=str(exc),
            data={"state": "unknown", "error": str(exc)},
        )
    if not project_key:
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="ERROR",
            title=_CUTOVER_TITLE,
            summary="could not resolve a canonical project key for artifact links",
            data={"state": "unknown"},
        )

    adapter = ArtifactLinkStore.from_sdd_store(store, project_key)
    try:
        inspection = inspect_artifact_link_cutover_markers(
            adapter.sidecar_roots,
            project_key=project_key,
        )
    except Exception as exc:  # noqa: BLE001 - malformed markers fail closed.
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="ERROR",
            title=_CUTOVER_TITLE,
            summary="artifact-link cutover marker is invalid",
            next_steps=(
                "Repair link-events/STORE.json in every document sidecar root "
                "before reading or writing artifact links."
            ),
            data={"state": "invalid", "error": str(exc)},
        )
    if inspection.marker is None:
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="OK",
            title=_CUTOVER_TITLE,
            summary="no artifact-link cutover marker present",
            data={"state": "none"},
        )
    if inspection.state == "incomplete":
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="ERROR",
            title=_CUTOVER_TITLE,
            summary="artifact-link cutover is incomplete",
            next_steps=(
                "Resume the import with `sase artifact link import-indexes --apply "
                "<attestation>` before reading or writing artifact links."
            ),
            data={
                "state": "incomplete",
                "import_id": inspection.marker.import_id,
                "roles": list(inspection.incomplete_roles),
                "diagnostics": list(inspection.diagnostics),
            },
        )

    stragglers = _cutover_links_tree_stragglers(adapter, inspection.marker)
    if stragglers:
        return DiagnosticCheck(
            id=_CUTOVER_CHECK_ID,
            group="project",
            status="ERROR",
            title=_CUTOVER_TITLE,
            summary="legacy links/ tree changed after artifact-link import",
            next_steps=(
                "Do not commit legacy links/ changes after import. Recreate "
                "the equivalent immutable link events, then restore the links/ "
                "tree to the frozen marker identity. Older SASE binaries do "
                "not understand link-events/STORE.json."
            ),
            data={
                "state": inspection.state,
                "import_id": inspection.marker.import_id,
                "stragglers": stragglers,
            },
        )

    return DiagnosticCheck(
        id=_CUTOVER_CHECK_ID,
        group="project",
        status="OK",
        title=_CUTOVER_TITLE,
        summary=f"artifact-link event store is {inspection.state}",
        next_steps=(
            ("Older SASE binaries do not understand link-events/STORE.json.",)
            if inspection.state == "fenced"
            else ()
        ),
        data={
            "state": inspection.state,
            "import_id": inspection.marker.import_id,
            "roles": [role.role for role in inspection.marker.roles],
        },
    )


def _cutover_links_tree_stragglers(
    adapter: ArtifactLinkStore,
    marker: ArtifactLinkCutoverMarker,
) -> list[dict[str, str]]:
    if marker.state != "imported":
        return []
    stragglers: list[dict[str, str]] = []
    for role in marker.roles:
        root = adapter.sidecar_roots.get(role.kind)
        if root is None:
            continue
        current = artifact_link_legacy_links_tree_identity(root)
        if current != role.links_tree:
            stragglers.append(
                {
                    "current_links_tree": current,
                    "frozen_links_tree": role.links_tree,
                    "role": role.role,
                }
            )
    return stragglers


def _collect_primary_sidecar_link_dirt(
    primary: Path, store: SddStore
) -> tuple[PrimarySidecarLinkDirt, ...]:
    """Return uncommitted ``links/`` dirt in sidecar clones nested under *primary*."""

    primary_root = _resolved(primary)
    if primary_root is None:
        return ()

    dirt: list[PrimarySidecarLinkDirt] = []
    seen: set[Path] = set()
    roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
    for role in roles:
        try:
            clone = store.repo_root_for_kind(role).expanduser().resolve(strict=False)
        except Exception:  # noqa: BLE001 - a doctor check never breaks the report.
            continue
        if clone in seen or not clone.is_dir():
            continue
        seen.add(clone)
        if clone == primary_root or not _is_nested_under(clone, primary_root):
            continue
        for xy, relpath in _porcelain_entries(clone):
            if not _is_links_path(relpath):
                continue
            dirt.append(
                PrimarySidecarLinkDirt(
                    role=role,
                    clone=clone,
                    path=relpath,
                    xy=xy,
                    restorable=_is_restorable_deletion(xy, relpath, clone),
                )
            )
    return tuple(dirt)


def plan_primary_sidecar_link_dirt_repairs(
    context: DoctorContext,
) -> tuple[PrimarySidecarLinkDirt, ...]:
    """Return restorable stranded link-index deletions under the primary checkout."""

    resolved = _resolve_primary_sidecar_store(context)
    if resolved is None:
        return ()
    primary, store = resolved
    return tuple(
        entry
        for entry in _collect_primary_sidecar_link_dirt(primary, store)
        if entry.restorable
    )


def apply_primary_sidecar_link_dirt_repairs(
    dirt: Sequence[PrimarySidecarLinkDirt],
) -> tuple[PrimarySidecarLinkDirtRepairResult, ...]:
    """Restore restorable link-index deletions without committing."""

    grouped: dict[Path, list[PrimarySidecarLinkDirt]] = {}
    for entry in dirt:
        if not entry.restorable:
            continue
        grouped.setdefault(entry.clone, []).append(entry)

    results: list[PrimarySidecarLinkDirtRepairResult] = []
    for clone, entries in grouped.items():
        paths = tuple(dict.fromkeys(entry.path for entry in entries))
        role = entries[0].role
        error = _restore_paths(clone, paths)
        results.append(
            PrimarySidecarLinkDirtRepairResult(
                role=role,
                clone=clone,
                restored=() if error else paths,
                error=error,
            )
        )
    return tuple(results)


def _resolve_primary_sidecar_store(
    context: DoctorContext,
) -> tuple[Path, SddStore] | None:
    try:
        from sase.sdd.checkout_anchor import resolve_checkout_anchor
        from sase.sdd.files import get_primary_workspace_dir
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store

        anchor = resolve_checkout_anchor(context.cwd)
        checkout, workspace_num = workspace_context_for_plan_resolution(
            anchor.primary_root
        )
        primary = (
            Path(get_primary_workspace_dir(str(checkout), workspace_num))
            .expanduser()
            .resolve(strict=False)
        )
        if not primary.is_dir():
            return None
        store = resolve_sdd_store(primary, 1)
    except Exception:  # noqa: BLE001 - a doctor check never breaks the report.
        return None
    if not store.is_sidecar_storage:
        return None
    return primary, store


def _porcelain_entries(clone: Path) -> tuple[tuple[str, str], ...]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(clone),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return ()
    if result.returncode != 0:
        return ()
    entries: list[tuple[str, str]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        path = line[3:]
        if path.startswith("./"):
            path = path[2:]
        entries.append((line[:2], path))
    return tuple(entries)


def _restore_paths(clone: Path, paths: Sequence[str]) -> str | None:
    if not paths:
        return None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(clone),
                "restore",
                "--worktree",
                "--staged",
                "--",
                *paths,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - surface the failure, do not raise.
        return f"{type(exc).__name__}: {exc}"
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
    return detail


def _is_links_path(relpath: str) -> bool:
    parts = Path(relpath).parts
    return bool(parts) and parts[0] == REFERENCED_BY_LINKS_DIR


def _is_restorable_deletion(xy: str, relpath: str, clone: Path) -> bool:
    if "D" not in xy:
        return False
    return is_canonical_artifact_link_index_location(clone / relpath, clone)


def _is_nested_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolved(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return None


def _dirt_detail(entry: PrimarySidecarLinkDirt) -> str:
    kind = "restorable deletion" if entry.restorable else "uncommitted"
    return f"{entry.role}: {entry.xy} {entry.path} ({kind})"


def _dirt_data(entry: PrimarySidecarLinkDirt) -> dict[str, object]:
    return {
        "role": entry.role,
        "clone": str(entry.clone),
        "path": entry.path,
        "xy": entry.xy,
        "restorable": entry.restorable,
    }


def _dirt_next_steps(
    restorable: Sequence[PrimarySidecarLinkDirt],
) -> tuple[str, ...]:
    steps = [
        "Dirt in a primary checkout's nested sidecar clone blocks pull-based "
        "sidecar auto-sync.",
        "Restore stranded link-index deletions rather than committing them; "
        "durable deletions land via the machine lane and reach the primary "
        "through auto-sync.",
    ]
    if restorable:
        steps.append(
            "Run `sase doctor -R` / `--fix-primary-sidecar-links` to restore "
            "those deletions as a user-origin action."
        )
        clone = restorable[0].clone
        paths = tuple(
            dict.fromkeys(entry.path for entry in restorable if entry.clone == clone)
        )
        steps.append(_restore_command(clone, paths))
    else:
        steps.append(
            "Inspect `git status` in the listed clone(s); this check does not "
            "auto-delete untracked files or revert non-deletion dirt."
        )
    return tuple(steps)


def _restore_command(clone: Path, paths: Sequence[str]) -> str:
    quoted_paths = " ".join(shlex.quote(path) for path in paths)
    return (
        f"git -C {shlex.quote(str(clone))} restore --worktree --staged -- "
        f"{quoted_paths}"
    )


__all__ = [
    "PrimarySidecarLinkDirt",
    "PrimarySidecarLinkDirtRepairResult",
    "apply_primary_sidecar_link_dirt_repairs",
    "artifact_links_check_specs",
    "plan_primary_sidecar_link_dirt_repairs",
]
