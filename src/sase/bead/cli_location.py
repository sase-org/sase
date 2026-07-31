"""Bead store discovery for CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING

from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
)
from sase.core.state_write_guard import pytest_path_is_sandboxed

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


@dataclass(frozen=True)
class BeadsLocation:
    """Resolved bead store location for the current workspace context."""

    root: Path
    beads_dirname: str
    storage: str | None = None
    store: SddStore | None = None
    read_only: bool = False
    expected_remote_url: str | None = None

    @property
    def beads_dir(self) -> Path:
        return self.root / self.beads_dirname

    @property
    def is_in_tree(self) -> bool:
        return self.beads_dirname == BEADS_DIRNAME


@dataclass(frozen=True)
class _WorkspaceContext:
    root: Path
    primary: Path
    workspace_num: int
    project_name: str | None = None


def find_beads_location(
    cwd: Path | None = None,
    *,
    materialize: bool = False,
) -> tuple[Path, str]:
    """Determine the beads root directory and subdirectory name.

    Uses the primary workspace and effective SDD mode to choose:
      - Local SDD: ``primary/.sase/sdd/beads/``
      - Separate-repo SDD: ``workspace/.sase/sdd/beads/``
      - VC: nearest ancestor containing ``sdd/beads/`` (or primary workspace)

    Falls back to legacy walk-up-from-cwd when no primary workspace is found.

    Returns (root_dir, beads_dirname) where root_dir / beads_dirname is the
    beads directory.
    """
    location = resolve_beads_location(cwd=cwd, materialize=materialize)
    if location is None:
        fallback = Path.cwd() if cwd is None else cwd
        return fallback, BEADS_DIRNAME
    return location.root, location.beads_dirname


def resolve_beads_location(
    cwd: Path | None = None,
    *,
    require_existing: bool = False,
    materialize: bool = False,
) -> BeadsLocation | None:
    """Resolve the bead store location for reads, writes, and commits."""
    current = (Path.cwd() if cwd is None else cwd).expanduser().resolve()
    context = _resolve_workspace_context(current)
    if context is not None:
        from sase.sdd.store import (
            SDD_STORAGE_SIDECAR_REPOS,
            SDD_STORAGE_IN_TREE,
            SDD_STORAGE_LOCAL,
            SDD_STORAGE_SEPARATE_REPO,
            SddStore,
            materialize_sdd_store,
            resolve_sdd_store,
        )

        if materialize:
            store = materialize_sdd_store(context.root, context.workspace_num)
            if (
                store.storage == SDD_STORAGE_SIDECAR_REPOS
                and store.beads_dir is not None
            ):
                from sase.sdd.store import ensure_beads_sidecar_clone

                ensure_beads_sidecar_clone(context.root, context.workspace_num)
        else:
            store = resolve_sdd_store(context.root, context.workspace_num)
        if store.storage == SDD_STORAGE_IN_TREE:
            root = _select_in_tree_beads_root(
                current,
                context.primary,
                require_existing=require_existing,
            )
            if root is None:
                return None
            return BeadsLocation(
                root=root,
                beads_dirname=BEADS_DIRNAME,
                storage=store.storage,
                store=store,
            )

        if store.storage == SDD_STORAGE_SIDECAR_REPOS:
            if store.beads_dir is not None:
                root = store.beads_dir
                beads_dirname = BEADS_DIRNAME_ROOT
                expected_remote_url = _recorded_beads_remote_url(context.primary)
            else:
                root = store.kind_root("plans")
                beads_dirname = BEADS_DIRNAME_NON_VC
                expected_remote_url = store.remote_url
        elif store.storage == SDD_STORAGE_SEPARATE_REPO:
            root = store.sdd_dir
            beads_dirname = BEADS_DIRNAME_NON_VC
            expected_remote_url = store.remote_url
        elif store.storage == SDD_STORAGE_LOCAL:
            root = context.primary / ".sase" / "sdd"
            beads_dirname = BEADS_DIRNAME_NON_VC
            expected_remote_url = None
            if store.sdd_dir != root:
                store = SddStore(
                    storage=store.storage,
                    sdd_dir=root,
                    repo_root=root,
                    provider=store.provider,
                    remote_url=store.remote_url,
                )
        else:
            root = context.primary / ".sase" / "sdd"
            beads_dirname = BEADS_DIRNAME_NON_VC
            expected_remote_url = None

        if require_existing and not bead_store_exists(root, beads_dirname):
            return None
        return BeadsLocation(
            root=root,
            beads_dirname=beads_dirname,
            storage=store.storage,
            store=store,
            expected_remote_url=expected_remote_url,
        )

    checkout_location = _resolve_checkout_record_beads_location(
        current,
        require_existing=require_existing,
    )
    if checkout_location is not None:
        return checkout_location

    return _resolve_legacy_beads_location(
        current,
        require_existing=require_existing,
    )


def _resolve_checkout_record_beads_location(
    cwd: Path,
    *,
    require_existing: bool,
) -> BeadsLocation | None:
    """Resolve a checkout-local sidecar record for read-only bead access."""
    from sase._linked_repo_paths import sidecar_repo_clone_dir
    from sase.sdd._store_records import read_sdd_store_record
    from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS

    for checkout_root in [cwd, *cwd.parents]:
        record = read_sdd_store_record(checkout_root)
        if record is None or not record.is_sidecar_storage:
            continue
        if record.has_split_beads:
            root = Path(sidecar_repo_clone_dir(checkout_root, "beads"))
            beads_dirname = BEADS_DIRNAME_ROOT
        else:
            root = Path(sidecar_repo_clone_dir(checkout_root, "plans"))
            beads_dirname = BEADS_DIRNAME_NON_VC
        if require_existing and not bead_store_exists(root, beads_dirname):
            return None
        return BeadsLocation(
            root=root,
            beads_dirname=beads_dirname,
            storage=SDD_STORAGE_SIDECAR_REPOS,
            read_only=True,
        )
    return None


def _recorded_beads_remote_url(primary: Path) -> str | None:
    """Return the authoritative remote for a recorded beads sidecar."""

    from sase.sdd._store_records import read_sdd_store_record

    record = read_sdd_store_record(primary)
    if record is None or record.beads is None:
        return None
    return record.beads.remote_url


def _resolve_workspace_context(cwd: Path) -> _WorkspaceContext | None:
    marker_context = _resolve_workspace_context_from_marker(cwd)
    if marker_context is not None:
        return marker_context

    scan_context = _resolve_workspace_context_from_project_scan(cwd)
    if scan_context is not None:
        return scan_context

    try:
        from sase.bead.workspace import resolve_primary_workspace

        primary = resolve_primary_workspace()
    except Exception:
        primary = None
    if primary is None:
        return None

    primary = primary.expanduser().resolve()
    if not pytest_path_is_sandboxed(primary):
        return None
    root = _existing_workspace_root(cwd) or _workspace_root_under_primary(cwd, primary)
    if root is None:
        root = cwd
    return _WorkspaceContext(root=root, primary=primary, workspace_num=1)


def _resolve_workspace_context_from_marker(cwd: Path) -> _WorkspaceContext | None:
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(cwd))
    except Exception:
        found = None
    if found is None:
        return None

    checkout_dir, marker = found
    primary = marker.primary_workspace_dir.strip()
    if not primary:
        return None
    resolved_primary = Path(primary.rstrip("/")).expanduser().resolve()
    if not pytest_path_is_sandboxed(resolved_primary):
        return None
    workspace_num = marker.workspace_num if marker.workspace_num > 0 else 1
    return _WorkspaceContext(
        root=Path(checkout_dir).expanduser().resolve(),
        primary=resolved_primary,
        workspace_num=workspace_num,
        project_name=marker.project_name or None,
    )


def _resolve_workspace_context_from_project_scan(cwd: Path) -> _WorkspaceContext | None:
    try:
        from sase.bead.project_name import scan_projects_for_cwd

        scanned = scan_projects_for_cwd(str(cwd))
    except Exception:
        scanned = None
    if scanned is None:
        return None

    project_name, primary = scanned
    primary = primary.expanduser().resolve()
    if not pytest_path_is_sandboxed(primary):
        return None
    root = (
        _workspace_root_from_primary_variant(cwd, primary, project_name)
        or _existing_workspace_root(cwd)
        or _workspace_root_under_primary(cwd, primary)
    )
    if root is None:
        return None
    return _WorkspaceContext(
        root=root,
        primary=primary,
        workspace_num=_workspace_num_from_root(root, project_name),
        project_name=project_name,
    )


def _select_in_tree_beads_root(
    cwd: Path,
    primary: Path,
    *,
    require_existing: bool,
) -> Path | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return parent
    primary_beads = primary / BEADS_DIRNAME
    if primary_beads.is_dir() or not require_existing:
        return primary
    return None


def _resolve_legacy_beads_location(
    cwd: Path,
    *,
    require_existing: bool,
) -> BeadsLocation | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return BeadsLocation(parent, BEADS_DIRNAME, storage="in_tree")
        non_vc = parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
        if non_vc.is_dir():
            return BeadsLocation(
                parent / ".sase" / "sdd",
                BEADS_DIRNAME_NON_VC,
                storage="local",
            )

    if require_existing:
        return None
    return BeadsLocation(cwd, BEADS_DIRNAME, storage="in_tree")


def _existing_workspace_root(cwd: Path) -> Path | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return parent
        if (parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC).is_dir():
            return parent
    return None


def _workspace_root_under_primary(cwd: Path, primary: Path) -> Path | None:
    try:
        cwd.relative_to(primary)
    except ValueError:
        return None
    return primary


def _workspace_root_from_primary_variant(
    cwd: Path,
    primary: Path,
    project_name: str,
) -> Path | None:
    primary_parts = primary.parts
    cwd_parts = cwd.parts
    if len(cwd_parts) < len(primary_parts):
        return None

    for index, primary_component in enumerate(primary_parts):
        cwd_component = cwd_parts[index]
        if primary_component == cwd_component:
            continue
        if _is_workspace_variant(
            primary_component, project_name
        ) and _is_workspace_variant(cwd_component, project_name):
            if tuple(cwd_parts[index + 1 : len(primary_parts)]) == tuple(
                primary_parts[index + 1 :]
            ):
                return Path(*cwd_parts[: len(primary_parts)])
        return None

    return primary


def _is_workspace_variant(component: str, project_name: str) -> bool:
    return component == project_name or component.startswith(f"{project_name}_")


def _workspace_num_from_root(root: Path, project_name: str | None) -> int:
    if not project_name:
        return 1
    pattern = re.compile(rf"^{re.escape(project_name)}_(\d+)$")
    for component in reversed(root.parts):
        match = pattern.match(component)
        if match:
            return int(match.group(1))
    return 1


def bead_store_exists(root: Path, beads_dirname: str) -> bool:
    beads_dir = root / beads_dirname
    if beads_dirname == BEADS_DIRNAME_ROOT:
        return (beads_dir / "config.json").is_file()
    return beads_dir.is_dir()


def resolved_beads_location_is_usable(location: BeadsLocation) -> bool:
    """Return whether a resolved warm store can be opened without materializing."""
    if not bead_store_exists(location.root, location.beads_dirname):
        return False
    store = location.store
    if store is None or location.is_in_tree:
        return True
    expected_remote_url = location.expected_remote_url or store.remote_url
    if not expected_remote_url:
        return True
    try:
        from sase.sdd._store_git import git_remote_url, same_git_remote

        origin = git_remote_url(location.root)
        return origin is not None and same_git_remote(origin, expected_remote_url)
    except Exception:
        return False
