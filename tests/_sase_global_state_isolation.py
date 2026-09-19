"""Test-only cleanup for process-global environment state."""

from __future__ import annotations

from collections.abc import Mapping
import os


_ENV_KEYS_TO_IGNORE = frozenset(
    {
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "PYTEST_CURRENT_TEST",
        "SASE_AXE_DISABLE_SYSTEMD_SCOPE",
        "SASE_DETACH_SCOPE_DISABLE",
        "SASE_PYTEST_SANDBOX_DIR",
    }
)
_ENV_KEY_PREFIXES_TO_IGNORE = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def _ignore_env_key(key: str) -> bool:
    return key in _ENV_KEYS_TO_IGNORE or key.startswith(_ENV_KEY_PREFIXES_TO_IGNORE)


def snapshot_sase_environment() -> dict[str, str]:
    """Return the process environment baseline for one test."""
    return {key: value for key, value in os.environ.items() if not _ignore_env_key(key)}


def restore_sase_environment(baseline: Mapping[str, str]) -> None:
    """Restore process env vars to a per-test baseline."""
    tracked_keys = {key for key in os.environ if not _ignore_env_key(key)} | set(
        baseline
    )
    for key in tracked_keys:
        baseline_value = baseline.get(key)
        if baseline_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = baseline_value
