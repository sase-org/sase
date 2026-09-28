"""Owned-row builders for the disk-footprint inventory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.config import get_managed_tmp_handoff_horizon_seconds
from sase.core._disk_footprint_inventory_shared import UNRESOLVED_PATH
from sase.core.disk_footprint_models import DISK_COVERAGE_COMPLETE
from sase.core.disk_footprint_models import DISK_COVERAGE_PARTIAL
from sase.core.disk_footprint_models import DISK_COVERAGE_UNRESOLVED
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_footprint_utils import InventoryScanBudget
from sase.core.disk_footprint_utils import format_horizon_seconds
from sase.core.disk_footprint_utils import iter_children
from sase.core.disk_footprint_utils import iter_children_bounded
from sase.core.disk_footprint_utils import normalize_path_no_follow
from sase.core.managed_tmp_reaper import current_managed_tmp_horizons
from sase.core.managed_tmp_roots import effective_managed_tmp_roots
from sase.core.paths import managed_tmpdir_root
from sase.core.paths import sase_home
from sase.core.paths import sase_projects_dir
from sase.procs.paths import procs_dir

#: Heavy sub-trees sized per workspace checkout so a clipped scan still
#: attributes bytes to the owning project instead of only the stray walk.
_WORKSPACE_HEAVY_CHILDREN = (
    ".git/objects",
    ".pytest_cache",
    "sase/repos",
    ".venv",
    "target",
)


def managed_tmp_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None = None,
    diagnostics: list[str] | None = None,
    roots: Sequence[Path] | None = None,
) -> tuple[DiskFootprintRow, ...]:
    """Size one row per bucket under every managed temp root writers used.

    The roots are the effective root unioned with every registered root
    from the root-registry phase, so a reaper running under a stale
    environment still attributes the bytes agents actually wrote.
    """

    resolved_roots = (
        tuple(roots) if roots is not None else tuple(_all_managed_tmp_roots())
    )
    horizons = current_managed_tmp_horizons()
    default_horizon = get_managed_tmp_handoff_horizon_seconds()
    rows: list[DiskFootprintRow] = []
    for root in resolved_roots:
        rows.extend(
            _managed_tmp_root_rows(
                root,
                tree_size_fn=tree_size_fn,
                budget=budget,
                diagnostics=diagnostics,
                horizons=horizons,
                default_horizon=default_horizon,
                qualify_name=len(resolved_roots) > 1,
            )
        )
    return tuple(rows)


def _all_managed_tmp_roots() -> list[Path]:
    """Return every managed temp root one inventory pass must cover."""

    try:
        return effective_managed_tmp_roots(
            effective_root=managed_tmpdir_root(),
            sase_home=sase_home(),
        )
    except Exception:  # noqa: BLE001 - inventory must stay fail-open.
        return [managed_tmpdir_root()]


def _managed_tmp_root_rows(
    root: Path,
    *,
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None,
    diagnostics: list[str] | None,
    horizons: Mapping[str, float],
    default_horizon: float,
    qualify_name: bool,
) -> list[DiskFootprintRow]:
    if not root.exists():
        return [
            DiskFootprintRow(
                section="managed_tmp",
                name="<root>",
                path=str(root),
                size_bytes=0,
                owner="managed_tmp_reaper",
                horizon="missing root",
                reclaim="sase disk reap --apply",
                physical_path=str(normalize_path_no_follow(root)),
            ),
        ]

    listing = iter_children_bounded(root, budget) if budget is not None else None
    children = listing.children if listing is not None else tuple(iter_children(root))
    root_diagnostics: tuple[str, ...] = ()
    root_coverage = DISK_COVERAGE_COMPLETE
    if listing is not None and not listing.complete:
        root_coverage = DISK_COVERAGE_PARTIAL
        root_diagnostics = (listing.error or "managed tmp root listing was clipped",)
        if diagnostics is not None:
            diagnostics.append(
                f"managed tmp root partial listing: {root_diagnostics[0]}"
            )

    rows: list[DiskFootprintRow] = []
    for entry in children:
        horizon_seconds = (
            horizons.get(entry.name, default_horizon)
            if entry.is_dir() and not entry.is_symlink()
            else default_horizon
        )
        rows.append(
            DiskFootprintRow(
                section="managed_tmp",
                name=(f"{root.name}/{entry.name}" if qualify_name else entry.name),
                path=str(entry),
                physical_path=str(normalize_path_no_follow(entry)),
                size_bytes=tree_size_fn(entry),
                owner="managed_tmp_reaper",
                horizon=format_horizon_seconds(horizon_seconds),
                reclaim="sase disk reap --apply",
                coverage=root_coverage,
                diagnostics=root_diagnostics,
            )
        )
    if root_coverage != DISK_COVERAGE_COMPLETE and not rows:
        rows.append(
            DiskFootprintRow(
                section="managed_tmp",
                name="<root>",
                path=str(root),
                physical_path=str(normalize_path_no_follow(root)),
                size_bytes=tree_size_fn(root),
                owner="managed_tmp_reaper",
                horizon="partially listed",
                reclaim="sase disk reap --apply",
                coverage=root_coverage,
                diagnostics=root_diagnostics,
            )
        )
    return rows


def sase_state_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None = None,
    diagnostics: list[str] | None = None,
) -> tuple[DiskFootprintRow, ...]:
    rows = [
        DiskFootprintRow(
            section="sase_home",
            name="procs/runtime",
            path=str(procs_dir() / "runtime"),
            physical_path=str(normalize_path_no_follow(procs_dir() / "runtime")),
            size_bytes=tree_size_fn(procs_dir() / "runtime"),
            owner="proc_runtime_sweep",
            horizon="proc row retention",
            reclaim="sase disk reap --apply",
        ),
        DiskFootprintRow(
            section="sase_home",
            name="tools",
            path=str(sase_home() / "tools"),
            physical_path=str(normalize_path_no_follow(sase_home() / "tools")),
            size_bytes=tree_size_fn(sase_home() / "tools"),
            owner="tool_run_retention",
            horizon="summary 180d, detail 60d, logs 14d after settlement",
            reclaim="sase disk reap --apply",
        ),
        DiskFootprintRow(
            section="sase_home",
            name="cache/rust-prebuild",
            path=str(sase_home() / "cache" / "rust-prebuild"),
            physical_path=str(
                normalize_path_no_follow(sase_home() / "cache" / "rust-prebuild")
            ),
            size_bytes=tree_size_fn(sase_home() / "cache" / "rust-prebuild"),
            owner="rust_prebuild_cache",
            horizon="keeps newest 2 completed sets",
            reclaim=None,
        ),
    ]
    months = get_artifact_retention_keep_recent_run_months()
    projects = sase_projects_dir()
    listing = iter_children_bounded(projects, budget) if budget is not None else None
    project_dirs = (
        listing.children if listing is not None else tuple(iter_children(projects))
    )
    project_coverage = DISK_COVERAGE_COMPLETE
    project_diagnostics: tuple[str, ...] = ()
    if listing is not None and not listing.complete:
        project_coverage = DISK_COVERAGE_PARTIAL
        project_diagnostics = (
            listing.error or "SASE projects root listing was clipped",
        )
        if diagnostics is not None:
            diagnostics.append(
                f"SASE projects root partial listing: {project_diagnostics[0]}"
            )
    for project_dir in project_dirs:
        if not project_dir.is_dir() or project_dir.is_symlink():
            continue
        ace_run = project_dir / "artifacts" / "ace-run"
        if not ace_run.exists():
            continue
        rows.append(
            DiskFootprintRow(
                section="sase_home",
                name=f"projects/{project_dir.name}/artifacts/ace-run",
                path=str(ace_run),
                physical_path=str(normalize_path_no_follow(ace_run)),
                size_bytes=tree_size_fn(ace_run),
                owner="artifact_run_retention",
                horizon=f"keeps newest {months} month(s) and referenced runs",
                reclaim="sase artifact prune-runs",
                coverage=project_coverage,
                diagnostics=project_diagnostics,
            )
        )
    return tuple(rows)


def workspace_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    workspace_inventory_fn: Callable[..., Any],
    diagnostics: list[str] | None = None,
) -> tuple[DiskFootprintRow, ...]:
    try:
        inventory = workspace_inventory_fn(include_disabled=True)
    except Exception as exc:
        message = f"workspace inventory discovery failed: {type(exc).__name__}: {exc}"
        if diagnostics is not None:
            diagnostics.append(message)
        return (
            DiskFootprintRow(
                section="workspaces",
                name="<workspace inventory>",
                path=UNRESOLVED_PATH,
                size_bytes=0,
                owner="workspace_cleanup_and_compact",
                horizon="unresolved workspace coverage",
                reclaim="sase workspace inventory",
                coverage=DISK_COVERAGE_UNRESOLVED,
                diagnostics=(message,),
            ),
        )
    rows: list[DiskFootprintRow] = []
    seen: set[str] = set()
    for issue in getattr(inventory, "issues", ()):
        project = getattr(issue, "project", "<unknown>")
        message = getattr(issue, "message", str(issue))
        if diagnostics is not None:
            diagnostics.append(f"workspace inventory issue for {project}: {message}")
    for project in getattr(inventory, "projects", ()):
        root_dir = Path(project.root_dir)
        key = str(normalize_path_no_follow(root_dir))
        if key in seen:
            continue
        rows.extend(
            _workspace_checkout_rows(
                label=str(project.project),
                checkout_dir=root_dir,
                tree_size_fn=tree_size_fn,
                seen=seen,
                owner="workspace_cleanup_and_compact",
                horizon=f"cleanup TTL {project.cleanup_ttl_days} day(s)",
                reclaim="sase workspace cleanup --stale; sase workspace compact",
            )
        )
        raw_primary_dir = getattr(project, "primary_workspace_dir", "") or ""
        primary_dir = Path(raw_primary_dir)
        if bool(getattr(project, "share_git_objects", True)) and raw_primary_dir:
            primary_key = str(normalize_path_no_follow(primary_dir))
            if primary_key not in seen:
                rows.extend(
                    _workspace_checkout_rows(
                        label=f"{project.project} primary",
                        checkout_dir=primary_dir,
                        tree_size_fn=tree_size_fn,
                        seen=seen,
                        owner="workspace_git_object_source",
                        horizon="shared Git object source; gc.pruneExpire=never",
                        reclaim=None,
                    )
                )
    return tuple(rows)


def _workspace_checkout_rows(
    *,
    label: str,
    checkout_dir: Path,
    tree_size_fn: Callable[[Path], int],
    seen: set[str],
    owner: str,
    horizon: str,
    reclaim: str | None,
) -> list[DiskFootprintRow]:
    """Size one workspace checkout plus its heavy sub-trees.

    The sub-rows nest under the checkout path, so the classifier reports
    each checkout once in the aggregate while still naming `.git/objects`,
    `.pytest_cache` (including `sase-visual`), `sase/repos`, `.venv`, and
    in-tree `target/` when they exist. Callers size these known locations
    before the generic stray walk, so a clipped scan still attributes the
    bytes to the owning project.
    """

    key = str(normalize_path_no_follow(checkout_dir))
    seen.add(key)
    rows = [
        DiskFootprintRow(
            section="workspaces",
            name=label,
            path=str(checkout_dir),
            physical_path=key,
            size_bytes=tree_size_fn(checkout_dir),
            owner=owner,
            horizon=horizon,
            reclaim=reclaim,
        )
    ]
    for child in _WORKSPACE_HEAVY_CHILDREN:
        child_dir = checkout_dir / child
        try:
            exists = child_dir.exists()
        except OSError:
            continue
        if not exists:
            continue
        child_key = str(normalize_path_no_follow(child_dir))
        if child_key in seen:
            continue
        seen.add(child_key)
        rows.append(
            DiskFootprintRow(
                section="workspaces",
                name=f"{label} {child}",
                path=str(child_dir),
                physical_path=child_key,
                size_bytes=tree_size_fn(child_dir),
                owner=owner,
                horizon=horizon,
                reclaim=reclaim,
            )
        )
    return rows


__all__ = [
    "managed_tmp_rows",
    "sase_state_rows",
    "workspace_rows",
]
