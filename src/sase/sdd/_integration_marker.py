"""Freshness marker shared by SDD integration callers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import time
from typing import Literal


BeadRefreshMode = Literal["background", "blocking", "off"]
_DEFAULT_REFRESH_TTL_SECONDS = 120.0
_INTEGRATION_MARKER = "sase-bead-sync.integration"


def bead_refresh_mode() -> BeadRefreshMode:
    """Return the configured remote-freshness policy for bead commands."""
    try:
        from sase.config import load_merged_config

        raw = (
            load_merged_config()
            .get("sdd", {})
            .get("bead_refresh", {})
            .get("mode", "background")
        )
    except Exception:
        return "background"
    return raw if raw in {"background", "blocking", "off"} else "background"


def bead_refresh_ttl_seconds() -> float:
    """Return the minimum age before another background sync is launched."""
    try:
        from sase.config import load_merged_config

        raw = (
            load_merged_config()
            .get("sdd", {})
            .get("bead_refresh", {})
            .get("ttl_seconds", _DEFAULT_REFRESH_TTL_SECONDS)
        )
        value = float(raw)
    except Exception:
        return _DEFAULT_REFRESH_TTL_SECONDS
    return max(0.0, value)


def mark_bead_integration(repo_root: Path) -> None:
    """Record a successful fetch/rebase integration for TTL gating."""
    marker = git_state_path(repo_root, _INTEGRATION_MARKER)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def integration_is_fresh(repo_root: Path) -> bool:
    """Return whether *repo_root* integrated within the configured TTL."""
    marker = git_state_path(repo_root, _INTEGRATION_MARKER)
    try:
        age = time.time() - marker.stat().st_mtime
    except OSError:
        return False
    return age < bead_refresh_ttl_seconds()


def integration_marker_generation(repo_root: Path) -> int | None:
    """Return the integration marker generation used to coalesce refreshes."""
    marker = git_state_path(repo_root, _INTEGRATION_MARKER)
    try:
        return marker.stat().st_mtime_ns
    except OSError:
        return None


def git_state_path(repo_root: Path, name: str) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    git_dir = Path(result.stdout.strip()) if result.returncode == 0 else Path(".git")
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    return git_dir / name if name else git_dir
