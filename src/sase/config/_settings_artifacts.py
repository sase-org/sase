"""Artifact capture and retention settings accessors."""

from __future__ import annotations

from typing import Any

from sase.config import _settings as _settings_facade


def _merged_config() -> dict[str, Any]:
    """Route through the facade so its patch point stays effective."""
    return _settings_facade.merged_config()


DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT = 50
DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN = 20
DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_ARTIFACT_RETENTION_EMPTY_SHARD_REMOVAL_BUDGET = 2000
DEFAULT_ARTIFACT_RETENTION_ENABLED = False
DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL = 3
DEFAULT_ARTIFACT_RETENTION_KEEP_RECENT_RUN_MONTHS = 2
DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS = 90
DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS = 14


def _artifact_capture_config() -> dict[str, Any]:
    artifacts = _merged_config().get("artifacts", {})
    capture = artifacts.get("capture", {}) if isinstance(artifacts, dict) else {}
    return capture if isinstance(capture, dict) else {}


def get_artifact_capture_max_stored_per_agent() -> int:
    """Return the validated per-run automatic artifact byte-copy cap."""
    value = _artifact_capture_config().get(
        "max_stored_per_agent",
        DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT


def get_artifact_capture_max_history_scan() -> int:
    """Return the validated VCS history-search bound for artifact capture."""
    value = _artifact_capture_config().get(
        "max_history_scan",
        DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN


def get_artifact_capture_max_file_size_bytes() -> int:
    """Return the maximum size of one pooled prompt artifact."""
    value = _artifact_capture_config().get(
        "max_file_size_bytes",
        DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES


def get_artifact_capture_pool_max_bytes() -> int:
    """Return the workspace-local prompt-artifact pool budget."""
    value = _artifact_capture_config().get(
        "pool_max_bytes",
        DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES


def _artifact_retention_config() -> dict[str, Any]:
    artifacts = _merged_config().get("artifacts", {})
    retention = artifacts.get("retention", {}) if isinstance(artifacts, dict) else {}
    return retention if isinstance(retention, dict) else {}


def get_artifact_retention_enabled() -> bool:
    """Return whether automatic artifact retention is enabled."""
    value = _artifact_retention_config().get(
        "enabled",
        DEFAULT_ARTIFACT_RETENTION_ENABLED,
    )
    if type(value) is bool:
        return value
    return DEFAULT_ARTIFACT_RETENTION_ENABLED


def get_artifact_retention_keep_per_label() -> int:
    """Return the validated automatic artifact generations kept per label."""
    value = _artifact_retention_config().get(
        "keep_per_label",
        DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL


def get_artifact_retention_empty_shard_removal_budget() -> int:
    """Return the max empty ACE-run shard dirs removed per retention apply."""
    value = _artifact_retention_config().get(
        "empty_shard_removal_budget",
        DEFAULT_ARTIFACT_RETENTION_EMPTY_SHARD_REMOVAL_BUDGET,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_RETENTION_EMPTY_SHARD_REMOVAL_BUDGET


def get_artifact_retention_keep_recent_run_months() -> int:
    """Return the validated full-month ACE-run retention horizon."""
    value = _artifact_retention_config().get(
        "keep_recent_run_months",
        DEFAULT_ARTIFACT_RETENTION_KEEP_RECENT_RUN_MONTHS,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_RETENTION_KEEP_RECENT_RUN_MONTHS


def get_artifact_retention_max_age_days() -> int:
    """Return the validated automatic artifact age bound in days."""
    value = _artifact_retention_config().get(
        "max_age_days",
        DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS


def get_artifact_retention_trash_grace_days() -> int:
    """Return the validated artifact trash grace period in days."""
    value = _artifact_retention_config().get(
        "trash_grace_days",
        DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS


__all__ = [
    "DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES",
    "DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN",
    "DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT",
    "DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES",
    "DEFAULT_ARTIFACT_RETENTION_EMPTY_SHARD_REMOVAL_BUDGET",
    "DEFAULT_ARTIFACT_RETENTION_ENABLED",
    "DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL",
    "DEFAULT_ARTIFACT_RETENTION_KEEP_RECENT_RUN_MONTHS",
    "DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS",
    "DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS",
    "get_artifact_capture_max_file_size_bytes",
    "get_artifact_capture_max_history_scan",
    "get_artifact_capture_max_stored_per_agent",
    "get_artifact_capture_pool_max_bytes",
    "get_artifact_retention_empty_shard_removal_budget",
    "get_artifact_retention_enabled",
    "get_artifact_retention_keep_per_label",
    "get_artifact_retention_keep_recent_run_months",
    "get_artifact_retention_max_age_days",
    "get_artifact_retention_trash_grace_days",
]
