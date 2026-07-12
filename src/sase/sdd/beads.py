"""Bead initialization for SDD projects."""

import subprocess
from pathlib import Path

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject
from sase.sdd._bead_ignore import ensure_bead_store_gitignore
from sase.sdd.files import get_primary_workspace_dir, commit_sdd_store_files
from sase.sdd.store import (
    SDD_STORAGE_LOCAL,
    SddStore,
    materialize_sdd_store,
    resolve_sdd_store,
)


def init_beads(workspace_dir: str, workspace_num: int) -> Path:
    """Bootstrap beads in the effective non-in-tree SDD repository.

    Legacy local stores use the primary workspace's `.sase/sdd/`; migrated
    stores use the plans companion root. The repository and `beads/` directory
    are initialized when missing.

    Returns the repository root containing `beads/`.
    """
    resolved_store = resolve_sdd_store(workspace_dir, workspace_num)
    if resolved_store.is_companion_storage:
        store = materialize_sdd_store(workspace_dir, workspace_num)
        sdd_dir = store.kind_root("plans")
    else:
        primary = get_primary_workspace_dir(workspace_dir, workspace_num)
        sdd_dir = Path(primary) / ".sase" / "sdd"
        store = (
            resolved_store
            if resolved_store.sdd_dir == sdd_dir
            else SddStore(SDD_STORAGE_LOCAL, sdd_dir, sdd_dir)
        )

    print(f"  Creating {sdd_dir}", flush=True)
    sdd_dir.mkdir(parents=True, exist_ok=True)

    if (sdd_dir / ".git").is_dir():
        print("  Git repo already initialized", flush=True)
    else:
        print("  Initializing git repo ...", flush=True)
        subprocess.run(
            ["git", "init"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )

    gitignore = sdd_dir / ".gitignore"
    if ensure_bead_store_gitignore(sdd_dir) is not None:
        print("  Writing .gitignore ...", flush=True)

    beads_dir = store.kind_root("beads")
    if beads_dir.is_dir():
        print("  Beads already initialized", flush=True)
    else:
        print("  Initializing beads ...", flush=True)
        BeadProject.init(sdd_dir, beads_dirname=BEADS_DIRNAME_NON_VC)

    commit_sdd_store_files(
        store,
        "Initialize beads",
        auto_commit_type="beads",
        paths=[gitignore, beads_dir],
    )

    return sdd_dir


def ensure_beads_initialized(workspace_dir: str, workspace_num: int) -> None:
    """Ensure beads are initialized, calling ``init_beads`` if necessary.

    For in-tree repos: initializes ``sdd/beads/`` in the primary workspace root.
    For other repos: delegates to ``init_beads()`` for ``.sase/sdd/beads/``.
    """
    primary = get_primary_workspace_dir(workspace_dir, workspace_num)
    store = materialize_sdd_store(workspace_dir, workspace_num)
    if store.is_in_tree:
        beads_dir = Path(primary, BEADS_DIRNAME)
        if not beads_dir.is_dir():
            from sase.sdd.files import ensure_bare_git_sdd_initialized

            ensure_bare_git_sdd_initialized(
                primary,
                commit=True,
                push=False,
            )
            BeadProject.init(Path(primary))
    else:
        beads_dir = store.kind_root("beads")
        if not beads_dir.is_dir():
            init_beads(workspace_dir, workspace_num)
