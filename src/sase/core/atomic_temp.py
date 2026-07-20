"""Best-effort cleanup for target-scoped atomic-write temp siblings."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

STALE_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60


def reap_stale_atomic_temps(
    target: Path,
    *,
    max_age_seconds: float = STALE_TEMP_MAX_AGE_SECONDS,
    now: float | None = None,
) -> None:
    """Remove only stale ``.<target>.*.tmp`` regular-file siblings.

    Cleanup is opportunistic: directory races, stat failures, and unlink failures
    are ignored so they can never prevent the caller's atomic write.
    """
    prefix = f".{target.name}."
    suffix = ".tmp"
    cutoff_now = time.time() if now is None else now
    try:
        siblings = list(target.parent.iterdir())
    except OSError:
        return
    for sibling in siblings:
        name = sibling.name
        if (
            not name.startswith(prefix)
            or not name.endswith(suffix)
            or len(name) <= len(prefix) + len(suffix)
        ):
            continue
        try:
            metadata = sibling.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                continue
            if cutoff_now - metadata.st_mtime <= max_age_seconds:
                continue
            sibling.unlink()
        except OSError:
            continue


__all__ = ["STALE_TEMP_MAX_AGE_SECONDS", "reap_stale_atomic_temps"]
