"""Configuration management for beads projects."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.bead.project_name import infer_project_name_from_cwd
from sase.config import load_merged_config


DEFAULT_BIG_EPIC_PHASE_THRESHOLD = 5


def get_big_epic_phase_threshold() -> int:
    """Return the configured authored-phase threshold for large epics.

    Missing or malformed values fall back to the shipped default. Booleans are
    rejected explicitly because ``bool`` is a subclass of ``int`` in Python,
    while the public configuration contract requires a positive integer.
    """
    try:
        merged: object = load_merged_config()
    except Exception:
        return DEFAULT_BIG_EPIC_PHASE_THRESHOLD
    if not isinstance(merged, dict):
        return DEFAULT_BIG_EPIC_PHASE_THRESHOLD

    bead_config = merged.get("bead", {})
    if not isinstance(bead_config, dict):
        return DEFAULT_BIG_EPIC_PHASE_THRESHOLD
    value = bead_config.get(
        "big_epic_phase_threshold",
        DEFAULT_BIG_EPIC_PHASE_THRESHOLD,
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_BIG_EPIC_PHASE_THRESHOLD
    return value


def _git_user_email() -> str:
    """Get the current git user email, or empty string."""
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()
    except FileNotFoundError:
        return ""


def _detect_prefix(root_dir: Path) -> str:
    """Detect issue prefix from git remote or directory name."""
    project_name = infer_project_name_from_cwd()
    if project_name:
        return project_name

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            cwd=root_dir,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            # Extract repo name from URL (handles both HTTPS and SSH)
            name = url.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except FileNotFoundError:
        pass
    return root_dir.resolve().name


def get_default_config(root_dir: Path) -> dict[str, object]:
    """Return default configuration values."""
    return {
        "issue_prefix": _detect_prefix(root_dir),
        "next_counter": 1,
        "owner": _git_user_email(),
    }


def load_config(beads_dir: Path) -> dict[str, object]:
    """Load config from beads/config.json. Returns defaults if missing."""
    config_path = beads_dir / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)  # type: ignore[no-any-return]
    return get_default_config(beads_dir.parent)


def save_config(beads_dir: Path, config: dict[str, object]) -> None:
    """Save config to beads/config.json."""
    config_path = beads_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
