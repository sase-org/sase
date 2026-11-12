"""Centralized configuration facade with multi-file merge support.

Loads ``default_config.yml`` (bundled in the package) as the base layer, then
plugin defaults, ``~/.config/sase/sase.yml``, machine-selected overlays, and
finally the current project's config.  Local config can be disabled with
``set_include_local_config(False)`` for processes such as ``sase tui``.

Low-level source IO and merging live in :mod:`sase.config.loading`; raw owner
selection lives in :mod:`sase.config.identity`; owner projections live in
:mod:`sase.config._owner` and per-value accessors in
:mod:`sase.config._settings`.  Cache state lives in :mod:`sase.config._cache`
and merged-config loaders in :mod:`sase.config._sources`.  This facade owns
the public API, including stale-while-revalidate freshness checks that keep
stat/glob IO off latency-sensitive render paths.  The submodules above read
back through this module rather than binding its state at import time, so
``sase.config.core`` remains the single patch point for every config read.
"""

from __future__ import annotations

import importlib.resources
import threading
import time
from pathlib import Path

from sase.config._cache import (
    CONFIG_TOKEN_REFRESH_THREAD_NAME,
    clear_config_cache,
    current_config_token,
    set_include_local_config,
    stat_token,
)
from sase.config._owner import (
    discover_machine_names,
    get_agent_owner_identity,
    get_local_machine_name,
    get_machine_name,
    require_agent_owner_identity,
    require_machine_name,
    selected_overlay_paths,
)
from sase.config._settings import (
    DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD,
    DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS,
    DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS,
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
    DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT,
    DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES,
    DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT,
    DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS,
    DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS,
    DEFAULT_MANAGED_TMP_DEAD_LAUNCH_ENABLED,
    DEFAULT_MANAGED_TMP_DEAD_LAUNCH_GRACE_SECONDS,
    DEFAULT_MANAGED_TMP_COMMAND_SCRATCH_HORIZON_SECONDS,
    DEFAULT_MANAGED_TMP_HANDOFF_HORIZON_SECONDS,
    DEFAULT_MANAGED_TMP_MAX_REMOVALS,
    DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS,
    DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS,
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES,
    DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL,
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES,
    DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES,
    DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS,
    DEFAULT_MAX_AGENT_PIPE_CHAIN,
    DEFAULT_MAX_RUNNING_AGENTS,
    DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
    DEFAULT_MONITOR_RAW_TAIL_LINES,
    DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
    DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
    DEFAULT_PROC_HISTORY_LIMIT,
    DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS,
    DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS,
    DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS,
    DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP,
    get_agent_hold_confirm_capture_threshold,
    get_agent_hold_default_ttl_seconds,
    get_agent_hold_max_ttl_seconds,
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
    get_disk_pressure_error_free_percent,
    get_disk_pressure_top_owner_min_bytes,
    get_disk_pressure_warn_free_percent,
    get_gate_turn_reclaim_grace_seconds,
    get_configured_max_running_agents,
    get_managed_tmp_agent_cargo_incremental,
    get_managed_tmp_build_scratch_horizon_seconds,
    get_managed_tmp_dead_launch_enabled,
    get_managed_tmp_dead_launch_grace_seconds,
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
    get_markdown_print_width,
    get_max_agent_pipe_chain,
    get_monitor_evidence_limits,
    get_pager_syntax,
    get_proc_history_limit,
    get_proc_runtime_orphan_horizon_seconds,
    get_proc_runtime_orphan_max_removals,
    get_runner_slot_deference_max_seconds,
    get_runner_slot_deference_seconds_per_step,
    get_task_history_limit,
    get_use_chezmoi,
)
from sase.config._sources import (
    get_agent_owner_config_snapshot,
    get_local_config_path,
    load_config_layers,
    load_macros_by_source,
    load_merged_config,
    load_merged_config_for_local_path,
    load_public_merged_config,
)
from sase.config.identity import (
    AgentOwnerConfigSnapshot,
    RawOverlayIdentity,
    build_agent_owner_config_snapshot,
    is_valid_machine_name,
    read_machine_name_selector,
    read_machine_name_selector_text,
)
from sase.config.layers import (
    DEPRECATED_TOP_LEVEL_KEYS,
    RETIRED_SDD_SELECTOR_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    ConfigLayer,
    load_yaml_file_with_metadata,
    without_project_only_keys,
    without_retired_sdd_selectors,
)
from sase.config.loading import merge_config_sources
from sase.markdown_width import DEFAULT_MARKDOWN_PRINT_WIDTH


CONFIG_DIR = Path("~/.config/sase").expanduser()
CHEZMOI_HOME = Path("~/.local/share/chezmoi/home").expanduser()


# Unlike its configured counterpart in :mod:`sase.config._settings`, this one
# stays on the facade so it resolves ``get_configured_max_running_agents``
# through this module's namespace, which callers patch.
def get_max_running_agents(now: float | None = None) -> int:
    """Return the live admission limit, preferring a temporary override.

    Override state errors propagate so admission callers fail closed for that
    poll rather than silently falling back to configuration.
    """
    from sase.config.runner_limit_override import get_active_runner_limit_override

    override = get_active_runner_limit_override(now)
    return (
        override.limit if override is not None else get_configured_max_running_agents()
    )


# Callables that used to be defined here keep this module as ``__module__``
# so unpatched-vs-patched detection (``sase.axe.config``) still sees the
# original facade after the split.
for _facade_symbol in (
    clear_config_cache,
    current_config_token,
    get_agent_owner_config_snapshot,
    get_local_config_path,
    load_config_layers,
    load_macros_by_source,
    load_merged_config,
    load_merged_config_for_local_path,
    load_public_merged_config,
    set_include_local_config,
    stat_token,
):
    _facade_symbol.__module__ = __name__
del _facade_symbol
