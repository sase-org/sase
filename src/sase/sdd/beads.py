"""Bead initialization for SDD projects."""

import subprocess
from pathlib import Path

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject
from sase.config import load_merged_config
from sase.sdd.files import get_primary_workspace_dir, commit_sdd_files
from sase.vcs_provider import detect_vcs


def get_sdd_config() -> bool:
    """Check if sdd.version_controlled is enabled in merged config."""
    config = load_merged_config()
    return bool(config.get("sdd", {}).get("version_controlled", False))


def get_effective_sdd_config(workspace_dir: str | Path | None = None) -> bool:
    """Return the effective SDD version-controlled mode.

    Bare-git workspaces always use version-controlled SDD, even when the
    merged config leaves ``sdd.version_controlled`` false. VCS detection is
    best-effort so config lookup remains non-fatal outside repositories.
    """
    configured = get_sdd_config()
    if configured:
        return True

    cwd = Path.cwd() if workspace_dir is None else Path(workspace_dir).expanduser()
    try:
        return detect_vcs(str(cwd)) == "bare_git"
    except Exception:
        return configured


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

    commit_sdd_files(
        sdd_dir,
        "Initialize beads",
        auto_commit_type="beads",
        paths=[gitignore, beads_dir],
    )

    return sdd_dir


def ensure_beads_initialized(workspace_dir: str, workspace_num: int) -> None:
    """Ensure beads are initialized, calling ``init_beads`` if necessary.

    For VC repos: initializes ``sdd/beads/`` in the primary workspace root.
    For non-VC repos: delegates to ``init_beads()`` for ``.sase/sdd/beads/``.
    """
    primary = get_primary_workspace_dir(workspace_dir, workspace_num)
    if get_effective_sdd_config(workspace_dir):
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
        beads_dir = Path(primary, ".sase", "sdd", BEADS_DIRNAME_NON_VC)
        if not beads_dir.is_dir():
            init_beads(workspace_dir, workspace_num)
