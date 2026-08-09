"""Cache for tracking when Patches were last checked for submission."""

import json
import time
from pathlib import Path

from sase.core.paths import sase_home

# Minimum interval between checks in seconds (5 minutes)
MIN_CHECK_INTERVAL_SECONDS = 5 * 60

# Cache file location
_CACHE_FILE: Path | None = None


def _cache_file() -> Path:
    return _CACHE_FILE or sase_home() / "sync_cache.json"


def _load_cache() -> dict[str, float]:
    """Load the sync cache from disk.

    Returns:
        Dictionary mapping Patch names to last_checked timestamps (Unix time).
    """
    path = _cache_file()
    if not path.exists():
        return {}

    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict[str, float]) -> None:
    """Save the sync cache to disk.

    Args:
        cache: Dictionary mapping Patch names to last_checked timestamps.
    """
    # Ensure parent directory exists
    path = _cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass  # Silently fail if we can't write the cache


def _get_last_checked(patch_name: str) -> float | None:
    """Get the last time a Patch was checked for submission.

    Args:
        patch_name: The NAME field value of the Patch.

    Returns:
        Unix timestamp of last check, or None if never checked.
    """
    cache = _load_cache()
    return cache.get(patch_name)


def update_last_checked(patch_name: str) -> None:
    """Update the last_checked timestamp for a Patch to now.

    Args:
        patch_name: The NAME field value of the Patch.
    """
    cache = _load_cache()
    cache[patch_name] = time.time()
    _save_cache(cache)


def should_check(patch_name: str, min_interval: int | None = None) -> bool:
    """Determine if a Patch should be checked for submission.

    A Patch should be checked if it has never been checked before,
    or if at least min_interval seconds have passed since the last check.

    Args:
        patch_name: The NAME field value of the Patch (or a cache key).
        min_interval: Minimum interval in seconds. Defaults to MIN_CHECK_INTERVAL_SECONDS.

    Returns:
        True if the Patch should be checked, False otherwise.
    """
    if min_interval is None:
        min_interval = MIN_CHECK_INTERVAL_SECONDS

    last_checked = _get_last_checked(patch_name)

    if last_checked is None:
        return True

    elapsed = time.time() - last_checked
    return elapsed >= min_interval


def clear_cache_entry(patch_name: str) -> None:
    """Remove a Patch from the cache.

    Useful when a Patch's status changes to Submitted.

    Args:
        patch_name: The NAME field value of the Patch.
    """
    cache = _load_cache()
    if patch_name in cache:
        del cache[patch_name]
        _save_cache(cache)
