"""Rust-target and stray cargo-target rows for the disk-footprint inventory."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Sequence
from pathlib import Path

from sase.core._disk_footprint_inventory_shared import STRAY_MAX_DEPTH
from sase.core._disk_footprint_inventory_shared import STRAY_MAX_VISITED
from sase.core._disk_footprint_inventory_shared import STRAY_SCAN_SECONDS
from sase.core.disk_footprint_models import DISK_COVERAGE_COMPLETE
from sase.core.disk_footprint_models import DISK_COVERAGE_PARTIAL
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_footprint_utils import InventoryScanBudget
from sase.core.disk_footprint_utils import is_relative_to
from sase.core.disk_footprint_utils import iter_children_bounded
from sase.core.disk_footprint_utils import normalize_path_no_follow

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
    max_depth: int = STRAY_MAX_DEPTH,
    max_visited: int = STRAY_MAX_VISITED,
    max_seconds: float = STRAY_SCAN_SECONDS,
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
    "is_cargo_target_root",
    "is_repo_checkout",
    "resolve_sase_core_dir",
    "resolve_sase_core_dirs",
    "rust_target_rows",
]
