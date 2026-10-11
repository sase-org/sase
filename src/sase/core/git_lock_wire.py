"""Wire records for Rust-backed Git index-lock recovery policy."""

from __future__ import annotations

from typing import Any

GIT_LOCK_WIRE_SCHEMA_VERSION = 1
"""Must match ``sase_core::git_lock``."""

GIT_LOCK_FAILURE_SUCCESS = "success"
GIT_LOCK_FAILURE_INDEX_LOCK = "index_lock"
GIT_LOCK_FAILURE_OTHER_LOCK = "other_lock"
GIT_LOCK_FAILURE_NOT_LOCK = "not_lock"

GIT_LOCK_OWNER_ACTIVE = "active"
GIT_LOCK_OWNER_ABSENT = "absent"
GIT_LOCK_OWNER_UNKNOWN = "unknown"

GIT_LOCK_ACTION_STOP = "stop"
GIT_LOCK_ACTION_RETRY = "retry"
GIT_LOCK_ACTION_WAIT = "wait"
GIT_LOCK_ACTION_REMOVE_THEN_RETRY = "remove_then_retry"
GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL = "retry_without_removal"

GIT_LOCK_FILE_REGULAR = "regular"
GIT_LOCK_FILE_SYMLINK = "symlink"
GIT_LOCK_FILE_DIRECTORY = "directory"
GIT_LOCK_FILE_OTHER = "other"
GIT_LOCK_FILE_MISSING = "missing"

GIT_LOCK_PROBE_COMPLETE = "complete"
GIT_LOCK_PROBE_INCOMPLETE = "incomplete"

DEFAULT_GIT_LOCK_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS = 15.0
DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS = 30.0


def require_git_lock_schema(data: dict[str, Any], *, what: str) -> None:
    """Raise when a Rust payload is stamped with a different schema."""
    schema_version = int(data["schema_version"])
    if schema_version != GIT_LOCK_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs git-lock {what} is stale: "
            f"expected schema {GIT_LOCK_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version}"
        )


__all__ = [
    "DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS",
    "DEFAULT_GIT_LOCK_RETRY_DELAYS",
    "GIT_LOCK_ACTION_REMOVE_THEN_RETRY",
    "GIT_LOCK_ACTION_RETRY",
    "GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL",
    "GIT_LOCK_ACTION_STOP",
    "GIT_LOCK_ACTION_WAIT",
    "GIT_LOCK_FAILURE_INDEX_LOCK",
    "GIT_LOCK_FAILURE_NOT_LOCK",
    "GIT_LOCK_FAILURE_OTHER_LOCK",
    "GIT_LOCK_FAILURE_SUCCESS",
    "GIT_LOCK_FILE_DIRECTORY",
    "GIT_LOCK_FILE_MISSING",
    "GIT_LOCK_FILE_OTHER",
    "GIT_LOCK_FILE_REGULAR",
    "GIT_LOCK_FILE_SYMLINK",
    "GIT_LOCK_OWNER_ABSENT",
    "GIT_LOCK_OWNER_ACTIVE",
    "GIT_LOCK_OWNER_UNKNOWN",
    "GIT_LOCK_PROBE_COMPLETE",
    "GIT_LOCK_PROBE_INCOMPLETE",
    "GIT_LOCK_WIRE_SCHEMA_VERSION",
    "STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS",
    "require_git_lock_schema",
]
