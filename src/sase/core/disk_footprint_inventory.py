"""Inventory collection for SASE-owned and SASE-shaped disk usage."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.config import (
    get_artifact_retention_keep_recent_run_months,
    get_disk_pressure_warn_free_percent,
    get_managed_tmp_handoff_horizon_seconds,
)
from sase.core.disk_pressure import ABSOLUTE_WARN_FREE_BYTES
from sase.core.managed_tmp_roots import (
    effective_managed_tmp_roots as _effective_managed_tmp_roots,
)
from sase.core.disk_footprint_models import (
    DISK_COVERAGE_COMPLETE,
    DISK_COVERAGE_PARTIAL,
    DISK_COVERAGE_UNRESOLVED,
    DiskFootprintReport,
    DiskFootprintRow,
)
from sase.core.disk_inventory import classify_disk_inventory
from sase.core.disk_footprint_utils import (
    BoundedTreeSizer,
    InventoryScanBudget,
    format_horizon_seconds,
    is_relative_to,
    iter_children,
    iter_children_bounded,
    normalize_path_no_follow,
    resolve_soft,
    tree_size,
)
from sase.core.managed_tmp_reaper import current_managed_tmp_horizons
from sase.core.paths import managed_tmpdir_root, sase_home, sase_projects_dir
from sase.core.time import local_now
from sase.procs.paths import procs_dir
from sase.workspace_provider.inventory import collect_workspace_inventory


effective_managed_tmp_roots = _effective_managed_tmp_roots

_GIB = 1024**3
_DEFAULT_STRAY_MAX_DEPTH = 6
_DEFAULT_STRAY_MAX_VISITED = 50_000
_DEFAULT_STRAY_SCAN_SECONDS = 5.0
_UNRESOLVED_PATH = ""

#: Heavy sub-trees sized per workspace checkout so a clipped scan still
#: attributes bytes to the owning project instead of only the stray walk.
_WORKSPACE_HEAVY_CHILDREN = (
    ".git/objects",
    ".pytest_cache",
    "sase/repos",
    ".venv",
    "target",
)

_UNATTRIBUTED_OWNER = "unattributed"


def collect_disk_footprint(
    *,
    include_strays: bool = True,
    home: Path | None = None,
    tree_size_fn: Callable[[Path], int] | None = None,
    workspace_inventory_fn: Callable[..., Any] = collect_workspace_inventory,
    now: datetime | None = None,
    disk_usage_fn: Callable[[str], Any] | None = None,
) -> DiskFootprintReport:
    """Collect SASE-owned and SASE-shaped disk usage rows.

    SASE-known heavy locations (managed roots, state, workspaces, rust
    targets) are always sized before the generic stray walk, so an
    exhausted shared scan budget can only clip the stray walk. When the
    scan is partial or the ``SASE_HOME`` filesystem is under pressure, an
    ``unattributed`` row accounts for ``df`` used minus attributed bytes.
    """

    rows: list[DiskFootprintRow] = []
    diagnostics: list[str] = []
    budget = InventoryScanBudget(
        max_nodes=_DEFAULT_STRAY_MAX_VISITED,
        max_seconds=_DEFAULT_STRAY_SCAN_SECONDS,
    )
    size_fn: Callable[[Path], int]
    if tree_size_fn is None:
        bounded_sizer = BoundedTreeSizer(budget=budget)
        size_fn = bounded_sizer.size
    else:
        bounded_sizer = None
        size_fn = tree_size_fn
    generated = (now or local_now()).isoformat()
    rows.extend(
        managed_tmp_rows(tree_size_fn=size_fn, budget=budget, diagnostics=diagnostics)
    )
    rows.extend(
        sase_state_rows(tree_size_fn=size_fn, budget=budget, diagnostics=diagnostics)
    )
    rows.extend(
        workspace_rows(
            tree_size_fn=size_fn,
            workspace_inventory_fn=workspace_inventory_fn,
            diagnostics=diagnostics,
        )
    )
    core_targets = rust_target_rows(tree_size_fn=size_fn)
    rows.extend(core_targets)

    stray_truncated = False
    stray_visited = 0
    if include_strays:
        excludes = [
            Path(row.path)
            for row in rows
            if row.status == "owned" and row.path and Path(row.path).is_absolute()
        ]
        strays, stray_visited, stray_truncated = cargo_stray_rows(
            home or Path.home(),
            excludes=excludes,
            tree_size_fn=size_fn,
            budget=budget,
        )
        rows.extend(strays)
        if stray_truncated:
            diagnostics.append(
                "stray cargo-target scan clipped before exhausting the home tree; "
                "unowned content may exist outside visited paths"
            )
        if stray_visited:
            diagnostics.append(
                f"stray cargo-target scan only descends {_DEFAULT_STRAY_MAX_DEPTH} "
                "levels below the scan root; deeper targets are excluded from proof"
            )

    diagnostics.extend(tuple(bounded_sizer.diagnostics) if bounded_sizer else ())
    report = _classified_report(
        rows,
        generated_at=generated,
        stray_scan_visited=stray_visited,
        stray_scan_truncated=stray_truncated or budget.truncated,
        scan_diagnostics=diagnostics,
    )
    unattributed = _unattributed_row(
        report,
        disk_usage_fn=disk_usage_fn or shutil.disk_usage,
    )
    if unattributed is not None:
        diagnostics.append(
            f"unattributed {unattributed.size_bytes} bytes on the SASE_HOME "
            "filesystem fall outside inventoried rows"
        )
        report = _classified_report(
            (*rows, unattributed),
            generated_at=generated,
            stray_scan_visited=stray_visited,
            stray_scan_truncated=stray_truncated or budget.truncated,
            scan_diagnostics=diagnostics,
        )
    return report


def largest_unowned_rows(
    *,
    min_bytes: int,
    limit: int = 3,
    report: DiskFootprintReport | None = None,
) -> tuple[DiskFootprintRow, ...]:
    """Return the largest unowned rows above *min_bytes*."""

    current = report or collect_disk_footprint(include_strays=True)
    rows = [
        row
        for row in current.rows
        if row.status == "unowned" and row.size_bytes >= min_bytes
    ]
    rows.sort(key=lambda row: (-row.size_bytes, row.path))
    return tuple(rows[: max(0, limit)])


def _classified_report(
    rows: Sequence[DiskFootprintRow],
    *,
    generated_at: str,
    stray_scan_visited: int,
    stray_scan_truncated: bool,
    scan_diagnostics: Sequence[str],
) -> DiskFootprintReport:
    classified = classify_disk_inventory(
        (row.to_json_dict() for row in rows),
        scan_diagnostics=scan_diagnostics,
        stray_scan_visited=stray_scan_visited,
        stray_scan_truncated=stray_scan_truncated,
    )
    classified_rows = [_row_from_wire(row) for row in classified["rows"]]
    classified_rows.sort(
        key=lambda row: (-row.size_bytes, row.section, row.name, row.path)
    )
    return DiskFootprintReport(
        rows=tuple(classified_rows),
        generated_at=generated_at,
        stray_scan_truncated=bool(classified["stray_scan_truncated"]),
        stray_scan_visited=int(classified["stray_scan_visited"]),
        scan_diagnostics=tuple(str(value) for value in classified["scan_diagnostics"]),
        physical_total_bytes=int(classified["total_bytes"]),
        logical_total_bytes=int(classified["logical_total_bytes"]),
        owned_total_bytes=int(classified["owned_total_bytes"]),
        unowned_total_bytes=int(classified["unowned_total_bytes"]),
        coverage_status=str(classified["coverage_status"]),
        unresolved_owner_coverage=tuple(
            str(value) for value in classified["unresolved_owner_coverage"]
        ),
    )


def _unattributed_row(
    report: DiskFootprintReport,
    *,
    disk_usage_fn: Callable[[str], Any],
) -> DiskFootprintRow | None:
    """Explain ``df`` used bytes that no inventoried row attributes.

    The row is emitted only when coverage is partial or the filesystem
    holding ``SASE_HOME`` is under pressure; otherwise attribution already
    accounts for the disk. It carries an empty path so the classifier
    cannot nest it under (or over) inventoried rows and double-count.
    """

    try:
        home = sase_home()
    except Exception:  # noqa: BLE001 - inventory must stay fail-open.
        return None
    try:
        usage = disk_usage_fn(str(home))
        total_bytes = int(usage.total)
        used_bytes = int(usage.used)
        free_bytes = int(usage.free)
    except Exception:  # noqa: BLE001 - inventory must stay fail-open.
        return None
    unattributed_bytes = used_bytes - _attributed_bytes_on(report, home)
    if unattributed_bytes <= 0:
        return None
    warn_threshold = max(
        ABSOLUTE_WARN_FREE_BYTES,
        int(total_bytes * get_disk_pressure_warn_free_percent() / 100.0),
    )
    partial = report.coverage_status != DISK_COVERAGE_COMPLETE
    if not partial and free_bytes > warn_threshold:
        return None
    return DiskFootprintRow(
        section="filesystem",
        name=_UNATTRIBUTED_OWNER,
        path=_UNRESOLVED_PATH,
        size_bytes=unattributed_bytes,
        owner=_UNATTRIBUTED_OWNER,
        horizon=(
            f"{'partial inventory coverage' if partial else 'filesystem pressure'}"
            "; bytes on the SASE_HOME filesystem outside inventoried rows"
        ),
        reclaim="sase disk list",
        coverage=(DISK_COVERAGE_PARTIAL if partial else DISK_COVERAGE_COMPLETE),
        diagnostics=(
            f"filesystem used {used_bytes} bytes; inventoried rows on this "
            f"filesystem attribute {used_bytes - unattributed_bytes} bytes",
        ),
    )


def _attributed_bytes_on(report: DiskFootprintReport, home: Path) -> int:
    """Sum attributed physical bytes residing on *home*'s filesystem."""

    try:
        home_dev = home.stat().st_dev
    except OSError:
        home_dev = None
    attributed = 0
    for row in report.rows:
        size = (
            row.exclusive_size_bytes
            if row.exclusive_size_bytes is not None
            else row.size_bytes
        )
        if not row.path or home_dev is None:
            attributed += size
            continue
        try:
            same_filesystem = Path(row.path).stat().st_dev == home_dev
        except OSError:
            same_filesystem = True
        if same_filesystem:
            attributed += size
    return attributed


def _row_from_wire(raw: Mapping[str, Any]) -> DiskFootprintRow:
    return DiskFootprintRow(
        section=str(raw["section"]),
        name=str(raw["name"]),
        path=str(raw["path"]),
        size_bytes=int(raw["size_bytes"]),
        owner=str(raw["owner"]),
        horizon=str(raw["horizon"]),
        status=str(raw.get("status") or "owned"),
        reclaim=raw.get("reclaim"),
        physical_path=raw.get("physical_path"),
        exclusive_size_bytes=int(raw["exclusive_size_bytes"]),
        coverage=str(raw.get("coverage") or DISK_COVERAGE_COMPLETE),
        diagnostics=tuple(str(value) for value in raw.get("diagnostics") or ()),
        overlap_parent_path=raw.get("overlap_parent_path"),
        overlap_paths=tuple(str(value) for value in raw.get("overlap_paths") or ()),
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
                path=_UNRESOLVED_PATH,
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


_RUST_DEV_BUILD_PROFILE = "dev-update"
"""Matches the Justfile's ``SASE_RUST_DEV_PROFILE`` default."""


def _rust_dev_build_profile() -> str:
    return os.environ.get("SASE_RUST_DEV_PROFILE") or _RUST_DEV_BUILD_PROFILE


def rust_target_rows(
    *, tree_size_fn: Callable[[Path], int]
) -> tuple[DiskFootprintRow, ...]:
    core_dirs = list(resolve_sase_core_dirs())
    legacy_core_dir = resolve_sase_core_dir()
    if legacy_core_dir is not None:
        legacy_key = str(normalize_path_no_follow(legacy_core_dir))
        if all(str(normalize_path_no_follow(path)) != legacy_key for path in core_dirs):
            core_dirs.insert(0, legacy_core_dir)
    if not core_dirs:
        return ()
    rows: list[DiskFootprintRow] = []
    profile = _rust_dev_build_profile()
    seen: set[str] = set()
    for core_dir in core_dirs:
        for name, target, build in _rust_recipe_targets(core_dir):
            for row in _rust_target_observation_rows(
                core_dir=core_dir,
                name=name,
                target=target,
                build=build,
                profile=profile,
                tree_size_fn=tree_size_fn,
            ):
                key = row.physical_path or str(normalize_path_no_follow(Path(row.path)))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    return tuple(rows)


def _rust_recipe_targets(core_dir: Path) -> tuple[tuple[str, Path, Path], ...]:
    targets = [
        (
            "uv-tool-lsp",
            core_dir / "target" / "uv-tool-lsp",
            core_dir / "target" / "uv-tool-lsp" / "build",
        ),
        (
            "uv-tool-py",
            core_dir / "target" / "uv-tool-py",
            core_dir / "target" / "uv-tool-py" / "build",
        ),
    ]
    env_target = os.environ.get("CARGO_TARGET_DIR")
    env_build = os.environ.get("CARGO_BUILD_BUILD_DIR")
    if env_target:
        target = Path(env_target).expanduser()
        build = Path(env_build).expanduser() if env_build else target / "build"
        targets.append(("env-cargo-target", target, build))
    return tuple(targets)


def _rust_target_observation_rows(
    *,
    core_dir: Path,
    name: str,
    target: Path,
    build: Path,
    profile: str,
    tree_size_fn: Callable[[Path], int],
) -> tuple[DiskFootprintRow, ...]:
    incremental = build / profile / "incremental"
    prefix = f"{core_dir.name}/target/{name}"
    return (
        DiskFootprintRow(
            section="rust_targets",
            name=prefix,
            path=str(target),
            physical_path=str(normalize_path_no_follow(target)),
            size_bytes=tree_size_fn(target),
            owner="just rust-dev-install",
            horizon="repo-owned persistent target root",
            reclaim=None,
        ),
        DiskFootprintRow(
            section="rust_targets",
            name=f"{prefix}/build",
            path=str(build),
            physical_path=str(normalize_path_no_follow(build)),
            size_bytes=tree_size_fn(build),
            owner="just rust-dev-install",
            horizon="cargo build scratch relocated by CARGO_BUILD_BUILD_DIR",
            reclaim=None,
        ),
        DiskFootprintRow(
            section="rust_targets",
            name=f"{prefix}/build/{profile}/incremental",
            path=str(incremental),
            physical_path=str(normalize_path_no_follow(incremental)),
            size_bytes=tree_size_fn(incremental),
            owner="just rust-dev-install",
            horizon="safe to delete; returns only when managed_tmp.agent_cargo_incremental is true",
            reclaim="rm -rf <incremental>",
        ),
    )


def cargo_stray_rows(
    home: Path,
    *,
    excludes: Sequence[Path],
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None = None,
    max_depth: int = _DEFAULT_STRAY_MAX_DEPTH,
    max_visited: int = _DEFAULT_STRAY_MAX_VISITED,
    max_seconds: float = _DEFAULT_STRAY_SCAN_SECONDS,
) -> tuple[tuple[DiskFootprintRow, ...], int, bool]:
    root = home.expanduser()
    if not root.is_dir():
        return (), 0, False
    local_budget = budget or InventoryScanBudget(
        max_nodes=max_visited,
        max_seconds=max_seconds,
    )
    rows: list[DiskFootprintRow] = []
    visited = 0
    truncated = False
    stack: list[tuple[Path, int]] = [(root, 0)]
    resolved_excludes = tuple(normalize_path_no_follow(path) for path in excludes)

    while stack:
        if not local_budget.consume_node():
            truncated = True
            break
        path, depth = stack.pop()
        visited += 1
        if visited > max_visited:
            truncated = True
            break
        if path.name in {".git", ".cargo", ".rustup"}:
            continue
        resolved = normalize_path_no_follow(path)
        if any(is_relative_to(resolved, excluded) for excluded in resolved_excludes):
            continue
        if path != root and is_repo_checkout(path):
            continue
        if path != root and is_cargo_target_root(path):
            rows.append(
                DiskFootprintRow(
                    section="strays",
                    name=path.name,
                    path=str(path),
                    physical_path=str(normalize_path_no_follow(path)),
                    size_bytes=tree_size_fn(path),
                    owner="unowned",
                    horizon="unowned",
                    status="unowned",
                    coverage=(
                        DISK_COVERAGE_PARTIAL if truncated else DISK_COVERAGE_COMPLETE
                    ),
                    reclaim=None,
                )
            )
            continue
        if depth >= max_depth:
            continue
        listing = iter_children_bounded(path, local_budget)
        if not listing.complete:
            truncated = True
        for child in reversed(listing.children):
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(
                child_stat.st_mode
            ):
                stack.append((child, depth + 1))
    return tuple(rows), visited, truncated


def resolve_sase_core_dir() -> Path | None:
    resolved = resolve_sase_core_dirs()
    return resolved[0] if resolved else None


def resolve_sase_core_dirs() -> tuple[Path, ...]:
    candidates: list[Path] = []
    for name in (
        "SASE_CORE_DIR",
        "SASE_LINKED_REPO_SASE_CORE_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_DIR",
        "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR",
    ):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value).expanduser())
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "sase" / "repos" / "linked" / "sase-core",
            cwd.parent / "sase-core",
        ]
    )
    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if (candidate / "Cargo.toml").is_file():
            normalized = normalize_path_no_follow(candidate)
            key = str(normalized)
            if key not in seen:
                seen.add(key)
                resolved.append(normalized)
    return tuple(resolved)


def is_cargo_target_root(path: Path) -> bool:
    return (path / ".rustc_info.json").is_file() or (path / "CACHEDIR.TAG").is_file()


def is_repo_checkout(path: Path) -> bool:
    return (path / ".git").exists()


__all__ = [
    "cargo_stray_rows",
    "collect_disk_footprint",
    "is_cargo_target_root",
    "is_repo_checkout",
    "largest_unowned_rows",
    "managed_tmp_rows",
    "resolve_sase_core_dir",
    "resolve_sase_core_dirs",
    "resolve_soft",
    "rust_target_rows",
    "sase_state_rows",
    "workspace_rows",
    "_GIB",
]
