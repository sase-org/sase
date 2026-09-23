"""Validated accessors for individual values held in the merged config.

Each accessor projects one merged-config value into a typed Python result and
falls back to the package default when the value is missing or malformed: a
hand-edited ``~/.config/sase/sase.yml`` must never turn a routine command into
a traceback.  Accessors that run on formatting or scheduling paths widen that
to catching load failures outright, which each one notes.

Reads go through :mod:`sase.config.core` rather than binding
``load_merged_config`` at import time so the facade keeps owning the cache and
remains the single patch point every accessor here honors.

The accessors live in section modules (:mod:`sase.config._settings_runner`,
:mod:`sase.config._settings_display`, :mod:`sase.config._settings_artifacts`,
and :mod:`sase.config._settings_system`); this module re-exports them so
existing ``sase.config._settings`` imports keep working.
"""

from __future__ import annotations

from typing import Any

from sase.config._settings_artifacts import (
    DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES,
    DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN,
    DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT,
    DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES,
    DEFAULT_ARTIFACT_RETENTION_EMPTY_SHARD_REMOVAL_BUDGET,
    DEFAULT_ARTIFACT_RETENTION_ENABLED,
    DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL,
    DEFAULT_ARTIFACT_RETENTION_KEEP_RECENT_RUN_MONTHS,
    DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS,
    DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS,
    get_artifact_capture_max_file_size_bytes,
    get_artifact_capture_max_history_scan,
    get_artifact_capture_max_stored_per_agent,
    get_artifact_capture_pool_max_bytes,
    get_artifact_retention_empty_shard_removal_budget,
    get_artifact_retention_enabled,
    get_artifact_retention_keep_per_label,
    get_artifact_retention_keep_recent_run_months,
    get_artifact_retention_max_age_days,
    get_artifact_retention_trash_grace_days,
)
from sase.config._settings_display import (
    DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
    DEFAULT_MONITOR_RAW_TAIL_LINES,
    DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
    DEFAULT_MONITOR_TOOL_WRAP,
    DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
    DEFAULT_PAGER_SYNTAX,
    MONITOR_TOOL_WRAP_CHOICES,
    get_markdown_print_width,
    get_monitor_evidence_limits,
    get_monitor_tool_wrap,
    get_pager_syntax,
)
from sase.config._settings_runner import (
    DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD,
    DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS,
    DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS,
    DEFAULT_MAX_AGENT_PIPE_CHAIN,
    DEFAULT_MAX_RUNNING_AGENTS,
    DEFAULT_PROC_HISTORY_LIMIT,
    DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS,
    DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS,
    DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS,
    DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP,
    get_agent_hold_confirm_capture_threshold,
    get_agent_hold_default_ttl_seconds,
    get_agent_hold_max_ttl_seconds,
    get_configured_max_running_agents,
    get_max_agent_pipe_chain,
    get_proc_history_limit,
    get_proc_runtime_orphan_horizon_seconds,
    get_proc_runtime_orphan_max_removals,
    get_runner_slot_deference_max_seconds,
    get_runner_slot_deference_seconds_per_step,
    get_use_chezmoi,
)
from sase.config._settings_system import (
    DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT,
    DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES,
    DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT,
    DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS,
    DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL,
    DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS,
    DEFAULT_MANAGED_TMP_COMMAND_SCRATCH_HORIZON_SECONDS,
    DEFAULT_MANAGED_TMP_HANDOFF_HORIZON_SECONDS,
    DEFAULT_MANAGED_TMP_MAX_REMOVALS,
    DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS,
    DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS,
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES,
    DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS,
    get_disk_pressure_error_free_percent,
    get_disk_pressure_top_owner_min_bytes,
    get_disk_pressure_warn_free_percent,
    get_gate_shell_reclaim_grace_seconds,
    get_managed_tmp_agent_cargo_incremental,
    get_managed_tmp_build_scratch_horizon_seconds,
    get_managed_tmp_command_scratch_horizon_seconds,
    get_managed_tmp_handoff_horizon_seconds,
    get_managed_tmp_max_removals,
    get_managed_tmp_pressure_low_free_space_min_age_seconds,
    get_managed_tmp_pressure_max_bytes,
    get_managed_tmp_pressure_min_age_seconds,
    get_managed_tmp_pressure_min_available_bytes,
    get_managed_tmp_pressure_min_entry_bytes,
    get_managed_tmp_pressure_recovery_available_bytes,
    get_managed_tmp_pressure_target_bytes,
    get_managed_tmp_run_artifact_horizon_seconds,
)


def _merged_config() -> dict[str, Any]:
    """Return the effective config through the ``sase.config.core`` facade.

    The import is deferred because ``core`` imports this module at load time.
    """
    from sase.config.core import load_merged_config

    return load_merged_config()


def merged_config() -> dict[str, Any]:
    """Return the effective config through :func:`_merged_config`.

    The section modules (:mod:`sase.config._settings_runner` and siblings)
    call this instead of sharing the private lookup, so the facade remains
    the single patch point every accessor honors.
    """
    return _merged_config()


# Legacy accessor alias; retire after every caller moves to the proc spelling.
get_task_history_limit = get_proc_history_limit


__all__ = [
    "DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD",
    "DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS",
    "DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS",
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
    "DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT",
    "DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES",
    "DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT",
    "DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS",
    "DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL",
    "DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS",
    "DEFAULT_MANAGED_TMP_COMMAND_SCRATCH_HORIZON_SECONDS",
    "DEFAULT_MANAGED_TMP_HANDOFF_HORIZON_SECONDS",
    "DEFAULT_MANAGED_TMP_MAX_REMOVALS",
    "DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS",
    "DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES",
    "DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS",
    "DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES",
    "DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES",
    "DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES",
    "DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES",
    "DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS",
    "DEFAULT_MAX_AGENT_PIPE_CHAIN",
    "DEFAULT_MAX_RUNNING_AGENTS",
    "DEFAULT_MONITOR_FALLBACK_TAIL_BYTES",
    "DEFAULT_MONITOR_RAW_TAIL_LINES",
    "DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES",
    "DEFAULT_MONITOR_TOOL_WRAP",
    "DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES",
    "DEFAULT_PAGER_SYNTAX",
    "DEFAULT_PROC_HISTORY_LIMIT",
    "DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS",
    "DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS",
    "DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS",
    "DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP",
    "MONITOR_TOOL_WRAP_CHOICES",
    "get_agent_hold_confirm_capture_threshold",
    "get_agent_hold_default_ttl_seconds",
    "get_agent_hold_max_ttl_seconds",
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
    "get_configured_max_running_agents",
    "get_disk_pressure_error_free_percent",
    "get_disk_pressure_top_owner_min_bytes",
    "get_disk_pressure_warn_free_percent",
    "get_gate_shell_reclaim_grace_seconds",
    "get_managed_tmp_agent_cargo_incremental",
    "get_managed_tmp_build_scratch_horizon_seconds",
    "get_managed_tmp_command_scratch_horizon_seconds",
    "get_managed_tmp_handoff_horizon_seconds",
    "get_managed_tmp_max_removals",
    "get_managed_tmp_pressure_low_free_space_min_age_seconds",
    "get_managed_tmp_pressure_max_bytes",
    "get_managed_tmp_pressure_min_age_seconds",
    "get_managed_tmp_pressure_min_available_bytes",
    "get_managed_tmp_pressure_min_entry_bytes",
    "get_managed_tmp_pressure_recovery_available_bytes",
    "get_managed_tmp_pressure_target_bytes",
    "get_managed_tmp_run_artifact_horizon_seconds",
    "get_markdown_print_width",
    "get_max_agent_pipe_chain",
    "get_monitor_evidence_limits",
    "get_monitor_tool_wrap",
    "get_pager_syntax",
    "get_proc_history_limit",
    "get_proc_runtime_orphan_horizon_seconds",
    "get_proc_runtime_orphan_max_removals",
    "get_runner_slot_deference_max_seconds",
    "get_runner_slot_deference_seconds_per_step",
    "get_task_history_limit",
    "get_use_chezmoi",
    "merged_config",
]
