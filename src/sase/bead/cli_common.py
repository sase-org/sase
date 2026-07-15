"""Shared helpers for bead CLI handlers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Literal

from sase.bead.model import Status
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BeadProject,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BeadsLocation:
    """Resolved bead store location for the current workspace context."""

    root: Path
    beads_dirname: str
    storage: str | None = None
    store: SddStore | None = None

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


def find_beads_location(*, materialize: bool = False) -> tuple[Path, str]:
    """Determine the beads root directory and subdirectory name.

    Uses the primary workspace and effective SDD mode to choose:
      - Local SDD: ``primary/.sase/sdd/beads/``
      - Separate-repo SDD: ``workspace/.sase/sdd/beads/``
      - VC: nearest ancestor containing ``sdd/beads/`` (or primary workspace)

    Falls back to legacy walk-up-from-cwd when no primary workspace is found.

    Returns (root_dir, beads_dirname) where root_dir / beads_dirname is the
    beads directory.
    """
    location = resolve_beads_location(materialize=materialize)
    if location is None:
        cwd = Path.cwd()
        return cwd, BEADS_DIRNAME
    return location.root, location.beads_dirname


def resolve_beads_location(
    cwd: Path | None = None,
    *,
    require_existing: bool = False,
    materialize: bool = False,
) -> _BeadsLocation | None:
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

        store = (
            materialize_sdd_store(context.root, context.workspace_num)
            if materialize
            else resolve_sdd_store(context.root, context.workspace_num)
        )
        if store.storage == SDD_STORAGE_IN_TREE:
            root = _select_in_tree_beads_root(
                current,
                context.primary,
                require_existing=require_existing,
            )
            if root is None:
                return None
            return _BeadsLocation(
                root=root,
                beads_dirname=BEADS_DIRNAME,
                storage=store.storage,
                store=store,
            )

        if store.storage == SDD_STORAGE_SIDECAR_REPOS:
            root = store.kind_root("plans")
        elif store.storage == SDD_STORAGE_SEPARATE_REPO:
            root = store.sdd_dir
        elif store.storage == SDD_STORAGE_LOCAL:
            root = context.primary / ".sase" / "sdd"
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

        if require_existing and not (root / BEADS_DIRNAME_NON_VC).is_dir():
            return None
        return _BeadsLocation(
            root=root,
            beads_dirname=BEADS_DIRNAME_NON_VC,
            storage=store.storage,
            store=store,
        )

    return _resolve_legacy_beads_location(
        current,
        require_existing=require_existing,
    )


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
    workspace_num = marker.workspace_num if marker.workspace_num > 0 else 1
    return _WorkspaceContext(
        root=Path(checkout_dir).expanduser().resolve(),
        primary=Path(primary.rstrip("/")).expanduser().resolve(),
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
) -> _BeadsLocation | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return _BeadsLocation(parent, BEADS_DIRNAME, storage="in_tree")
        non_vc = parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
        if non_vc.is_dir():
            return _BeadsLocation(
                parent / ".sase" / "sdd",
                BEADS_DIRNAME_NON_VC,
                storage="local",
            )

    if require_existing:
        return None
    return _BeadsLocation(cwd, BEADS_DIRNAME, storage="in_tree")


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


def init_beads(root: Path, beads_dirname: str) -> None:
    """Initialize beads at the given location.

    For non-VC mode, bootstraps a standalone git repo inside the SDD directory.
    """
    if beads_dirname == BEADS_DIRNAME:
        from sase.sdd.files import ensure_bare_git_sdd_initialized

        ensure_bare_git_sdd_initialized(root, commit=True, push=False)
    if beads_dirname == BEADS_DIRNAME_NON_VC:
        import subprocess

        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").is_dir():
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        from sase.sdd._bead_ignore import ensure_bead_store_gitignore

        ensure_bead_store_gitignore(root)
    with BeadProject.init(root, beads_dirname=beads_dirname):
        pass
    if beads_dirname == BEADS_DIRNAME_NON_VC:
        from sase.sdd.files import commit_sdd_files

        commit_sdd_files(root, "Initialize beads", auto_commit_type="beads")


def get_project() -> BeadProject:
    """Open the BeadProject for write operations, auto-initializing if needed."""
    location = resolve_beads_location(require_existing=True)
    from sase.bead.sync import bead_refresh_mode

    if (
        location is None
        or not resolved_beads_location_is_usable(location)
        or bead_refresh_mode() == "blocking"
    ):
        location = resolve_beads_location(materialize=True)

    if location is None:
        root, beads_dirname = find_beads_location(materialize=True)
    else:
        root, beads_dirname = location.root, location.beads_dirname
    beads_path = root / beads_dirname
    if not beads_path.exists():
        init_beads(root, beads_dirname)
    return BeadProject(root, beads_dirname=beads_dirname)


def get_read_view() -> BeadProject:
    """Open the same single bead store used by write commands."""
    return get_project()


def resolved_beads_location_is_usable(location: _BeadsLocation) -> bool:
    """Return whether a resolved warm store can be opened without materializing."""
    if not location.beads_dir.is_dir():
        return False
    store = location.store
    if store is None or location.is_in_tree or not store.remote_url:
        return True
    try:
        from sase.sdd._store_link import is_matching_store_clone

        return is_matching_store_clone(location.root, store)
    except Exception:
        return False


def auto_commit_bead_store(
    message: str,
    *,
    push_after_commit: bool | Literal["async"] | None = None,
) -> None:
    """Best-effort commit/push for non-in-tree SDD bead store mutations."""
    try:
        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import SddStore

        location = resolve_beads_location(require_existing=True)
        if location is None or location.is_in_tree:
            return
        store = location.store or SddStore(
            storage="local",
            sdd_dir=location.root,
            repo_root=location.root,
        )
        if push_after_commit is None:
            commit_sdd_store_files(
                store,
                message,
                auto_commit_type="beads",
                paths=[location.beads_dir],
            )
        else:
            commit_sdd_store_files(
                store,
                message,
                auto_commit_type="beads",
                paths=[location.beads_dir],
                push_after_commit=push_after_commit,
            )
    except Exception:
        _logger.warning(
            "Failed to auto-commit SDD bead store changes",
            exc_info=True,
        )


def normalize_workspace_path(resolved: Path) -> Path:
    """Normalize a path from an ephemeral workspace to the primary workspace.

    If ``resolved`` is inside a sibling workspace (same parent directory as the
    primary workspace), rewrite it to be rooted at the primary workspace instead.
    This prevents ephemeral ``sase_<N>`` prefixes from leaking into stored paths.
    """
    from sase.bead.workspace import resolve_primary_workspace

    primary = resolve_primary_workspace()
    if not primary:
        return resolved

    try:
        resolved.relative_to(primary)
        return resolved  # already inside primary
    except ValueError:
        pass

    # Check if inside a sibling workspace (same parent directory)
    try:
        rel_to_parent = resolved.relative_to(primary.parent)
    except ValueError:
        return resolved  # not in a sibling workspace

    parts = rel_to_parent.parts
    if len(parts) > 1:
        return primary / Path(*parts[1:])
    return resolved


def storage_plan_path(resolved: Path) -> str:
    """Return the plan path representation to persist on a bead.

    Workspace-local plan paths are stored relative to the effective project
    root. External paths remain absolute after workspace-prefix normalization.
    """
    normalized = normalize_workspace_path(resolved)

    for root in _storage_relative_roots():
        try:
            return str(normalized.relative_to(root))
        except ValueError:
            continue

    return str(normalized)


def _storage_relative_roots() -> list[Path]:
    """Trusted roots that can produce stable storage-relative plan paths."""
    from sase.bead.workspace import resolve_primary_workspace

    roots: list[Path] = []
    primary = resolve_primary_workspace()
    if primary:
        roots.append(primary.resolve())
        return roots

    root, _beads_dirname = find_beads_location()
    roots.append(root.resolve())

    cwd = Path.cwd().resolve()
    if cwd not in roots:
        roots.append(cwd)

    return roots


def status_icon(status: Status) -> str:
    return {"open": "○", "in_progress": "◐", "closed": "✓"}[status.value]


# --- Subcommand handlers ---
