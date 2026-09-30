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


def get_attachment_sensitive_patterns() -> list[str]:
    """Return extra sensitive-path globs for bead note attachments.

    Reads ``bead.attachments.sensitive_patterns`` from the merged config.
    Missing or malformed values fail open to ``[]``: the core sensitive-path
    policy still applies, only the user extras are dropped.
    """
    try:
        merged: object = load_merged_config()
    except Exception:
        return []
    if not isinstance(merged, dict):
        return []
    bead_config = merged.get("bead", {})
    if not isinstance(bead_config, dict):
        return []
    attachments = bead_config.get("attachments", {})
    if not isinstance(attachments, dict):
        return []
    patterns = attachments.get("sensitive_patterns", [])
    if not isinstance(patterns, list):
        return []
    return [
        pattern for pattern in patterns if isinstance(pattern, str) and pattern.strip()
    ]


DEFAULT_ATTACHMENT_GIT_MAX_BYTES = 52428800
MAX_ATTACHMENT_GIT_MAX_BYTES = 99614720


def _attachment_config() -> dict[str, object]:
    """Return the merged ``bead.attachments`` config section, or ``{}``."""
    try:
        merged: object = load_merged_config()
    except Exception:
        return {}
    if not isinstance(merged, dict):
        return {}
    bead_config = merged.get("bead", {})
    if not isinstance(bead_config, dict):
        return {}
    attachments = bead_config.get("attachments", {})
    if not isinstance(attachments, dict):
        return {}
    return attachments


def get_attachment_git_max_bytes() -> int:
    """Return the configured git-tier ceiling, failing open to the default.

    Missing, malformed, or above 95 MiB fails open to 50 MiB, matching the
    other bead accessors. Booleans are rejected explicitly because ``bool``
    is a subclass of ``int``.
    """
    value = _attachment_config().get("git_max_bytes", DEFAULT_ATTACHMENT_GIT_MAX_BYTES)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_ATTACHMENT_GIT_MAX_BYTES
    ):
        return DEFAULT_ATTACHMENT_GIT_MAX_BYTES
    return value


def get_attachment_require_upload() -> bool:
    """Return whether attachment uploads must precede the bead event write.

    Missing or malformed values fail open to False.
    """
    value = _attachment_config().get("require_upload", False)
    if not isinstance(value, bool):
        return False
    return value


DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES = 26214400
DEFAULT_ATTACHMENT_BACKGROUND_UPLOAD_MIN_BYTES = 67108864
DEFAULT_ATTACHMENT_LARGE_MAX_BYTES = 2147483648


def get_attachment_auto_fetch_max_bytes() -> int:
    """Return the configured auto-fetch ceiling, failing open to the default.

    Missing or malformed values fail open to 25 MiB. Booleans are rejected
    explicitly because ``bool`` is a subclass of ``int``.
    """
    value = _attachment_config().get(
        "auto_fetch_max_bytes", DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES
    return value


def get_attachment_background_upload_min_bytes() -> int:
    """Return the size at which uploads move to the background worker.

    Missing or malformed values fail open to 64 MiB. Booleans are rejected
    explicitly because ``bool`` is a subclass of ``int``.
    """
    value = _attachment_config().get(
        "background_upload_min_bytes",
        DEFAULT_ATTACHMENT_BACKGROUND_UPLOAD_MIN_BYTES,
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_ATTACHMENT_BACKGROUND_UPLOAD_MIN_BYTES
    return value


def get_attachment_large_store() -> dict[str, object] | None:
    """Return the configured rclone large-object store, or None.

    The value is ``{"remote": "<rclone remote:path>", "max_bytes": 2 GiB}``.
    Missing, malformed, or remote-less values fail open to None: the git
    tier alone serves placement and oversized objects stay local-only.
    """
    value = _attachment_config().get("large_store", None)
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    remote = value.get("remote")
    if not isinstance(remote, str) or not remote.strip():
        return None
    max_bytes = value.get("max_bytes", DEFAULT_ATTACHMENT_LARGE_MAX_BYTES)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        max_bytes = DEFAULT_ATTACHMENT_LARGE_MAX_BYTES
    return {"remote": remote.strip(), "max_bytes": max_bytes}


def get_show_images_default() -> str:
    """Return the configured ``bead.show.images`` mode, or ``auto``.

    Missing or malformed values fail open to ``auto``: ``read``, JSON, and
    piped ``show`` never draw regardless of this setting.
    """
    try:
        from sase.bead.show_images import DEFAULT_SHOW_IMAGES, SHOW_IMAGE_MODES

        from sase.config import load_merged_config as _load_merged
    except Exception:
        return "auto"
    try:
        merged: object = _load_merged()
    except Exception:
        return "auto"
    if not isinstance(merged, dict):
        return "auto"
    bead_config = merged.get("bead", {})
    if not isinstance(bead_config, dict):
        return "auto"
    show = bead_config.get("show", {})
    if not isinstance(show, dict):
        return "auto"
    value = show.get("images", DEFAULT_SHOW_IMAGES)
    if not isinstance(value, str):
        return "auto"
    normalized = value.strip().lower()
    return normalized if normalized in SHOW_IMAGE_MODES else "auto"


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
    """Return the global +1 bar a ready task bead needs for a TaskTriage gate.

    This is the fallback bar: an untyped task bead, or one whose task type
    this machine does not have registered, uses this value; a bead with a
    known task type uses that type's own ``triage.min_plus_ones`` instead
    (see :func:`sase.bead.task_triage_policy.effective_min_plus_ones`).

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
