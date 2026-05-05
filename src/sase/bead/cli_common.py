"""Shared helpers for bead CLI handlers."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import Status
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BeadProject,
)
from sase.bead.workspace import MergedBeadView, get_project_beads_dirs


def find_beads_location() -> tuple[Path, str]:
    """Determine the beads root directory and subdirectory name.

    Uses the primary workspace and ``sdd.version_controlled`` config to choose:
      - Non-VC (default): ``primary/.sase/sdd/beads/``
      - VC: ``sdd/beads/`` in CWD (or primary workspace)

    Falls back to legacy walk-up-from-cwd when no primary workspace is found.

    Returns (root_dir, beads_dirname) where root_dir / beads_dirname is the
    beads directory.
    """
    from sase.bead.workspace import resolve_primary_workspace

    cwd = Path.cwd()

    primary = resolve_primary_workspace()
    if primary:
        from sase.sdd.beads import get_sdd_config

        if get_sdd_config():
            # VC mode: sdd/beads/ — prefer CWD copy, then primary.
            if (cwd / BEADS_DIRNAME).is_dir():
                return cwd, BEADS_DIRNAME
            return primary, BEADS_DIRNAME
        else:
            # Non-VC mode: always primary/.sase/sdd/beads/
            return primary / ".sase" / "sdd", BEADS_DIRNAME_NON_VC

    # No primary workspace — legacy walk-up from cwd.
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return parent, BEADS_DIRNAME
        non_vc = parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
        if non_vc.is_dir():
            return parent / ".sase" / "sdd", BEADS_DIRNAME_NON_VC

    return cwd, BEADS_DIRNAME


def init_beads(root: Path, beads_dirname: str) -> None:
    """Initialize beads at the given location.

    For non-VC mode, bootstraps a standalone git repo inside the SDD directory.
    """
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
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("beads/beads.db\n", encoding="utf-8")
    with BeadProject.init(root, beads_dirname=beads_dirname):
        pass
    if beads_dirname == BEADS_DIRNAME_NON_VC:
        from sase.sdd.files import commit_sdd_files

        commit_sdd_files(root, "Initialize beads")


def get_project() -> BeadProject:
    """Open the BeadProject for write operations, auto-initializing if needed."""
    root, beads_dirname = find_beads_location()
    beads_path = root / beads_dirname
    if not beads_path.exists():
        init_beads(root, beads_dirname)
    return BeadProject(root, beads_dirname=beads_dirname)


def get_read_view() -> MergedBeadView | BeadProject:
    """Get a merged read view across all workspaces.

    Falls back to the local BeadProject if workspace resolution fails.
    """
    beads_dirs = get_project_beads_dirs()
    if beads_dirs:
        return MergedBeadView(beads_dirs)
    return get_project()


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
