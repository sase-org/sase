"""Configuration management for beads projects."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.bead.prefix_policy import default_issue_prefix
from sase.config import load_merged_config


DEFAULT_BIG_EPIC_PHASE_THRESHOLD = 5
DEFAULT_TASK_TRIAGE_MIN_PLUS_ONES = 1
DEFAULT_TASK_TRIAGE_STALE_AFTER_DAYS = 7
DEFAULT_TASK_TRIAGE_STALE_CLEANUP_MIN_BEADS = 10


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


def _task_triage_config() -> dict[str, object]:
    """Return the merged ``bead.task_triage`` config section, or ``{}``.

    Any failure to load the merged config, or a non-``dict`` merged config,
    ``bead`` section, or ``task_triage`` section, is folded into an empty
    dict, leaving each accessor's own floor to supply the shipped default.
    """
    try:
        merged: object = load_merged_config()
    except Exception:
        return {}
    if not isinstance(merged, dict):
        return {}

    bead_config = merged.get("bead", {})
    if not isinstance(bead_config, dict):
        return {}

    task_triage = bead_config.get("task_triage", {})
    if not isinstance(task_triage, dict):
        return {}
    return task_triage


def get_task_triage_min_plus_ones() -> int:
    """Return the configured +1 bar a ready task bead needs for a TaskTriage gate.

    Missing or malformed values fall back to the shipped default. Booleans are
    rejected explicitly because ``bool`` is a subclass of ``int`` in Python.
    """
    value = _task_triage_config().get(
        "min_plus_ones", DEFAULT_TASK_TRIAGE_MIN_PLUS_ONES
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return DEFAULT_TASK_TRIAGE_MIN_PLUS_ONES
    return value


def get_task_triage_stale_after_days() -> int:
    """Return the configured age, in days, at which a sub-threshold task bead is stale.

    Missing or malformed values fall back to the shipped default. Booleans are
    rejected explicitly because ``bool`` is a subclass of ``int`` in Python.
    """
    value = _task_triage_config().get(
        "stale_after_days", DEFAULT_TASK_TRIAGE_STALE_AFTER_DAYS
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_TASK_TRIAGE_STALE_AFTER_DAYS
    return value


def get_task_triage_stale_cleanup_min_beads() -> int:
    """Return the configured stale-bead count that triggers a cleanup gate.

    Missing or malformed values fall back to the shipped default. Booleans are
    rejected explicitly because ``bool`` is a subclass of ``int`` in Python.
    """
    value = _task_triage_config().get(
        "stale_cleanup_min_beads", DEFAULT_TASK_TRIAGE_STALE_CLEANUP_MIN_BEADS
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_TASK_TRIAGE_STALE_CLEANUP_MIN_BEADS
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
    """Detect issue prefix from the project name, git remote, or directory name."""
    return default_issue_prefix(root_dir)


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
