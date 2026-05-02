"""Bead initialization for SDD projects."""

import subprocess
from pathlib import Path

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject
from sase.config import load_merged_config
from sase.sdd.files import get_primary_workspace_dir, commit_sdd_files


def get_sdd_config() -> bool:
    """Check if sdd.version_controlled is enabled in merged config."""
    config = load_merged_config()
    return bool(config.get("sdd", {}).get("version_controlled", False))


def init_beads(workspace_dir: str, workspace_num: int) -> Path:
    """Bootstrap `.sase/sdd/` as a standalone git repo for local SDD tracking.

    1. Creates `.sase/sdd/` in the primary workspace.
    2. Runs `git init` inside it if not already a git repo.
    3. Runs `bd init --quiet --skip-hooks` in the primary workspace if `beads/` missing.

    Returns the `.sase/sdd/` path.
    """
    primary = get_primary_workspace_dir(workspace_dir, workspace_num)
    sdd_dir = Path(primary) / ".sase" / "sdd"

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
    if not gitignore.exists():
        print("  Writing .gitignore ...", flush=True)
        gitignore.write_text("beads/beads.db\n", encoding="utf-8")

    beads_dir = sdd_dir / BEADS_DIRNAME_NON_VC
    if beads_dir.is_dir():
        print("  Beads already initialized", flush=True)
    else:
        print("  Initializing beads ...", flush=True)
        BeadProject.init(sdd_dir, beads_dirname=BEADS_DIRNAME_NON_VC)

    commit_sdd_files(sdd_dir, "Initialize beads")

    return sdd_dir


def ensure_beads_initialized(workspace_dir: str, workspace_num: int) -> None:
    """Ensure beads are initialized, calling ``init_beads`` if necessary.

    For VC repos: initializes ``sdd/beads/`` in the primary workspace root.
    For non-VC repos: delegates to ``init_beads()`` for ``.sase/sdd/beads/``.
    """
    primary = get_primary_workspace_dir(workspace_dir, workspace_num)
    if get_sdd_config():
        beads_dir = Path(primary, BEADS_DIRNAME)
        if not beads_dir.is_dir():
            BeadProject.init(Path(primary))
    else:
        beads_dir = Path(primary, ".sase", "sdd", BEADS_DIRNAME_NON_VC)
        if not beads_dir.is_dir():
            init_beads(workspace_dir, workspace_num)
