"""Git sync for beads issue tracking."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_sync(beads_dir: Path) -> None:
    """Export JSONL and stage in git (does not commit)."""
    jsonl_path = beads_dir / "issues.jsonl"
    if not jsonl_path.exists():
        return
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return
    # Stage the JSONL file
    subprocess.run(
        ["git", "add", str(jsonl_path)],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )


def sync_status(beads_dir: Path) -> bool:
    """Check if JSONL has unstaged changes. Returns True if clean.

    Only checks for unstaged (working-tree) changes, since staged changes
    are expected — they will be included in the next ccommit.
    """
    jsonl_path = beads_dir / "issues.jsonl"
    if not jsonl_path.exists():
        return True
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return True
    result = subprocess.run(
        ["git", "diff", "--quiet", str(jsonl_path)],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def rebuild_from_jsonl(beads_dir: Path) -> bool:
    """Rebuild SQLite from JSONL if JSONL is newer than db.

    Returns True if rebuild was performed.
    """
    from sase.bead import db as db_mod
    from sase.bead.jsonl import import_from_jsonl

    jsonl_path = beads_dir / "issues.jsonl"
    db_path = beads_dir / "beads.db"

    if not jsonl_path.exists():
        return False

    # Rebuild if db doesn't exist or JSONL is newer
    if db_path.exists():
        jsonl_mtime = jsonl_path.stat().st_mtime
        db_mtime = db_path.stat().st_mtime
        if db_mtime >= jsonl_mtime:
            return False

    conn = db_mod.init_db(db_path)
    try:
        import_from_jsonl(jsonl_path, conn)
    finally:
        conn.close()
    return True


def _find_git_root(path: Path) -> Path | None:
    """Find the git root directory from a given path."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path if path.is_dir() else path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return None
