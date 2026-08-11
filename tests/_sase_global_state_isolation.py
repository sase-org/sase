"""Test-only cleanup for process-global environment state."""

from __future__ import annotations

from collections.abc import Mapping
import os


_ENV_KEYS_TO_IGNORE = frozenset({"PYTEST_CURRENT_TEST", "SASE_PYTEST_SANDBOX_DIR"})


def snapshot_sase_environment() -> dict[str, str]:
    """Return the process environment baseline for one test."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_KEYS_TO_IGNORE
    }


def restore_sase_environment(baseline: Mapping[str, str]) -> None:
    """Restore process env vars to a per-test baseline."""
    tracked_keys = {key for key in os.environ if key not in _ENV_KEYS_TO_IGNORE} | set(
        baseline
    )
    for key in tracked_keys:
        baseline_value = baseline.get(key)
        if baseline_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = baseline_value
