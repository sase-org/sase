"""Disk-pressure, managed-tmp, and gate-turn settings accessors."""

from __future__ import annotations

from typing import Any

from sase.config import _settings as _settings_facade


def _merged_config() -> dict[str, Any]:
    """Route through the facade so its patch point stays effective."""
    return _settings_facade.merged_config()


DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT = 1.0
DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES = 1024 * 1024 * 1024
DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT = 5.0
DEFAULT_MANAGED_TMP_COMMAND_SCRATCH_HORIZON_SECONDS = 12 * 3600
DEFAULT_MANAGED_TMP_HANDOFF_HORIZON_SECONDS = 3 * 24 * 3600
DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS = 24 * 3600
DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS = 14 * 24 * 3600
DEFAULT_MANAGED_TMP_MAX_REMOVALS = 2000
DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES = 32 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES = 48 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS = 12 * 3600
DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS = 3600
DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES = 64 * 1024 * 1024
DEFAULT_MANAGED_TMP_DEAD_LAUNCH_ENABLED = True
DEFAULT_MANAGED_TMP_DEAD_LAUNCH_GRACE_SECONDS = 2 * 3600
DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL = False
DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS = 3600


def _disk_pressure_config() -> dict[str, Any]:
    disk = _merged_config().get("disk", {})
    pressure = disk.get("pressure", {}) if isinstance(disk, dict) else {}
    return pressure if isinstance(pressure, dict) else {}


def get_disk_pressure_error_free_percent() -> float:
    """Return the error threshold as percent free space."""
    value = _disk_pressure_config().get(
        "error_free_percent",
        DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT,
    )
    if type(value) in {int, float} and 0 <= float(value) <= 100:
        return float(value)
    return DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT


def get_disk_pressure_top_owner_min_bytes() -> int:
    """Return the minimum row size named in disk-pressure next steps."""
    value = _disk_pressure_config().get(
        "top_owner_min_bytes",
        DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES


def get_disk_pressure_warn_free_percent() -> float:
    """Return the warning threshold as percent free space."""
    value = _disk_pressure_config().get(
        "warn_free_percent",
        DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT,
    )
    if type(value) in {int, float} and 0 <= float(value) <= 100:
        return float(value)
    return DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT


def _managed_tmp_config() -> dict[str, Any]:
    value = _merged_config().get("managed_tmp", {})
    return value if isinstance(value, dict) else {}


def _managed_tmp_horizons_config() -> dict[str, Any]:
    horizons = _managed_tmp_config().get("horizons", {})
    return horizons if isinstance(horizons, dict) else {}


def _managed_tmp_pressure_config() -> dict[str, Any]:
    pressure = _managed_tmp_config().get("pressure", {})
    return pressure if isinstance(pressure, dict) else {}


def _managed_tmp_nonnegative_seconds(value: Any, default: float) -> float:
    if type(value) in {int, float} and value >= 0:
        return float(value)
    return default


def get_managed_tmp_command_scratch_horizon_seconds() -> float:
    """Return the age horizon for scratch whose reader is its own command."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_horizons_config().get("command_scratch_seconds"),
        DEFAULT_MANAGED_TMP_COMMAND_SCRATCH_HORIZON_SECONDS,
    )


def get_managed_tmp_handoff_horizon_seconds() -> float:
    """Return the age horizon for files a launched child process re-reads."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_horizons_config().get("handoff_seconds"),
        DEFAULT_MANAGED_TMP_HANDOFF_HORIZON_SECONDS,
    )


def get_managed_tmp_build_scratch_horizon_seconds() -> float:
    """Return the age horizon for one launched agent's Cargo/build scratch."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_horizons_config().get("build_scratch_seconds"),
        DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS,
    )


def get_managed_tmp_run_artifact_horizon_seconds() -> float:
    """Return the age horizon for runs the ACE Agents tab reads back."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_horizons_config().get("run_artifact_seconds"),
        DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS,
    )


def get_managed_tmp_max_removals() -> int:
    """Return the validated per-invocation removal budget."""
    value = _managed_tmp_config().get(
        "max_removals",
        DEFAULT_MANAGED_TMP_MAX_REMOVALS,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MANAGED_TMP_MAX_REMOVALS


def get_managed_tmp_pressure_max_bytes() -> int | None:
    """Return the managed-root size that triggers pressure pruning.

    ``0`` disables the size trigger.
    """
    value = _managed_tmp_pressure_config().get(
        "max_bytes",
        DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES,
    )
    if type(value) is int and value == 0:
        return None
    if type(value) is int and value > 0:
        return value
    return DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES


def get_managed_tmp_pressure_target_bytes() -> int:
    """Return the managed-root size the pressure pass tries to return to."""
    value = _managed_tmp_pressure_config().get(
        "target_bytes",
        DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES


def get_managed_tmp_pressure_min_available_bytes() -> int | None:
    """Return the free-space floor that triggers pressure pruning.

    ``0`` disables the free-space trigger.
    """
    value = _managed_tmp_pressure_config().get(
        "min_available_bytes",
        DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES,
    )
    if type(value) is int and value == 0:
        return None
    if type(value) is int and value > 0:
        return value
    return DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES


def get_managed_tmp_pressure_recovery_available_bytes() -> int:
    """Return the free-space target used after crossing the low-space floor."""
    value = _managed_tmp_pressure_config().get(
        "recovery_available_bytes",
        DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES


def get_managed_tmp_pressure_min_age_seconds() -> float:
    """Return the minimum age before pressure can prune a large scratch entry."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_pressure_config().get("min_age_seconds"),
        DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS,
    )


def get_managed_tmp_pressure_low_free_space_min_age_seconds() -> float:
    """Return the emergency pressure age used after crossing the free-space floor."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_pressure_config().get("low_free_space_min_age_seconds"),
        DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS,
    )


def get_managed_tmp_pressure_min_entry_bytes() -> int:
    """Return the minimum entry size that participates in pressure pruning."""
    value = _managed_tmp_pressure_config().get(
        "min_entry_bytes",
        DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES


def _managed_tmp_dead_launch_config() -> dict[str, Any]:
    dead_launch = _managed_tmp_config().get("dead_launch", {})
    return dead_launch if isinstance(dead_launch, dict) else {}


def get_managed_tmp_dead_launch_enabled() -> bool:
    """Return whether the dead-launch backstop pass runs in the reaper."""
    value = _managed_tmp_dead_launch_config().get(
        "enabled",
        DEFAULT_MANAGED_TMP_DEAD_LAUNCH_ENABLED,
    )
    if type(value) is bool:
        return value
    return DEFAULT_MANAGED_TMP_DEAD_LAUNCH_ENABLED


def get_managed_tmp_dead_launch_grace_seconds() -> float:
    """Return the quiet age before dead launch scratch may be reaped."""
    return _managed_tmp_nonnegative_seconds(
        _managed_tmp_dead_launch_config().get("grace_seconds"),
        DEFAULT_MANAGED_TMP_DEAD_LAUNCH_GRACE_SECONDS,
    )


def get_managed_tmp_agent_cargo_incremental() -> bool:
    """Return whether launched agents get incremental Cargo check/clippy.

    Only hosts with the splitting rustc wrapper (athena) should opt in;
    elsewhere incremental test builds cost ~9 GB per run.
    """
    value = _managed_tmp_config().get(
        "agent_cargo_incremental",
        DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL,
    )
    if type(value) is bool:
        return value
    return DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL


DEFAULT_AGENT_SCOPE_TEARDOWN_ENABLED = True
DEFAULT_AGENT_SCOPE_TEARDOWN_TERM_GRACE_SECONDS = 3.0
DEFAULT_AGENT_SCOPE_TEARDOWN_REAPER_MIN_SCOPE_AGE_SECONDS = 120.0
DEFAULT_AGENT_SCOPE_TEARDOWN_SPARE_PROCESS_PATTERNS: tuple[str, ...] = (
    "^ssh-agent$",
    "^gpg-agent$",
    "^tmux: server$",
    r"^ssh: .*\[mux\]$",
)


DEFAULT_AGENT_AUTO_RESTART_ENABLED = True
DEFAULT_AGENT_AUTO_RESTART_QUIESCENCE_SECONDS = 30.0
DEFAULT_AGENT_AUTO_RESTART_MAX_DEFER_SECONDS = 1800.0
DEFAULT_AGENT_AUTO_RESTART_PENDING_RESURFACE_SECONDS = 600.0
DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_EPISODE = 12
DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_30M = 20


def _agent_scope_teardown_config() -> dict[str, Any]:
    value = _merged_config().get("agent_scope_teardown", {})
    return value if isinstance(value, dict) else {}


def _agent_auto_restart_config() -> dict[str, Any]:
    value = _merged_config().get("agent_auto_restart", {})
    return value if isinstance(value, dict) else {}


def get_agent_auto_restart_enabled() -> bool:
    """Return the master kill switch for automatic update-skew restarts."""
    value = _agent_auto_restart_config().get(
        "enabled",
        DEFAULT_AGENT_AUTO_RESTART_ENABLED,
    )
    if type(value) is bool:
        return value
    return DEFAULT_AGENT_AUTO_RESTART_ENABLED


def get_agent_auto_restart_quiescence_seconds() -> float:
    """Return the required seconds of code quiet before a relaunch."""
    value = _agent_auto_restart_config().get(
        "quiescence_seconds",
        DEFAULT_AGENT_AUTO_RESTART_QUIESCENCE_SECONDS,
    )
    if type(value) in {int, float} and float(value) >= 0:
        return float(value)
    return DEFAULT_AGENT_AUTO_RESTART_QUIESCENCE_SECONDS


def get_agent_auto_restart_max_defer_seconds() -> float:
    """Return the maximum age of a deferred record before it is declined."""
    value = _agent_auto_restart_config().get(
        "max_defer_seconds",
        DEFAULT_AGENT_AUTO_RESTART_MAX_DEFER_SECONDS,
    )
    if type(value) in {int, float} and float(value) >= 0:
        return float(value)
    return DEFAULT_AGENT_AUTO_RESTART_MAX_DEFER_SECONDS


def get_agent_auto_restart_pending_resurface_seconds() -> float:
    """Return the age after which a pending failure is re-surfaced loudly."""
    value = _agent_auto_restart_config().get(
        "pending_resurface_seconds",
        DEFAULT_AGENT_AUTO_RESTART_PENDING_RESURFACE_SECONDS,
    )
    if type(value) in {int, float} and float(value) >= 0:
        return float(value)
    return DEFAULT_AGENT_AUTO_RESTART_PENDING_RESURFACE_SECONDS


def get_agent_auto_restart_storm_max_per_episode() -> int:
    """Return the per-episode launch cap before the storm breaker trips."""
    value = _agent_auto_restart_config().get(
        "storm_max_per_episode",
        DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_EPISODE,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_EPISODE


def get_agent_auto_restart_storm_max_per_30m() -> int:
    """Return the rolling-30-minute launch cap before the storm breaker trips."""
    value = _agent_auto_restart_config().get(
        "storm_max_per_30m",
        DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_30M,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_30M


def get_agent_scope_teardown_enabled() -> bool:
    """Return whether the runner sweeps its own agent scope."""
    value = _agent_scope_teardown_config().get(
        "enabled",
        DEFAULT_AGENT_SCOPE_TEARDOWN_ENABLED,
    )
    if type(value) is bool:
        return value
    return DEFAULT_AGENT_SCOPE_TEARDOWN_ENABLED


def get_agent_scope_teardown_term_grace_seconds() -> float:
    """Return the SIGTERM-to-SIGKILL grace for scope sweeps."""
    value = _agent_scope_teardown_config().get(
        "term_grace_seconds",
        DEFAULT_AGENT_SCOPE_TEARDOWN_TERM_GRACE_SECONDS,
    )
    if type(value) in {int, float} and float(value) >= 0:
        return float(value)
    return DEFAULT_AGENT_SCOPE_TEARDOWN_TERM_GRACE_SECONDS


def get_agent_scope_teardown_reaper_min_scope_age_seconds() -> float:
    """Return the minimum scope age the orphaned-scope reaper may sweep."""
    value = _agent_scope_teardown_config().get(
        "reaper_min_scope_age_seconds",
        DEFAULT_AGENT_SCOPE_TEARDOWN_REAPER_MIN_SCOPE_AGE_SECONDS,
    )
    if type(value) in {int, float} and float(value) >= 0:
        return float(value)
    return DEFAULT_AGENT_SCOPE_TEARDOWN_REAPER_MIN_SCOPE_AGE_SECONDS


def get_agent_scope_teardown_spare_process_patterns() -> list[str]:
    """Return the spare-process regex list for scope sweeps."""
    value = _agent_scope_teardown_config().get(
        "spare_process_patterns",
        list(DEFAULT_AGENT_SCOPE_TEARDOWN_SPARE_PROCESS_PATTERNS),
    )
    if isinstance(value, list) and all(type(item) is str for item in value):
        return list(value)
    return list(DEFAULT_AGENT_SCOPE_TEARDOWN_SPARE_PROCESS_PATTERNS)


def get_gate_turn_reclaim_grace_seconds() -> int:
    """Return the grace period before a missed gate-turn deadline is lost."""
    try:
        gate = _merged_config().get("gate", {})
    except Exception:  # noqa: BLE001 - maintenance cleanup should fail open.
        return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
    if not isinstance(gate, dict):
        return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
    # Authored config follows the sunset flag: a retired
    # ``gate.shell.reclaim_grace_seconds`` maps to the turn key while the
    # flag is on and raises naming ``gate.turn.reclaim_grace_seconds``
    # while it is off, matching unknown-key reporting.
    from sase.agent.legacy_sase_shell_syntax import normalize_reclaim_config

    gate = normalize_reclaim_config({"gate": gate}).get("gate", {})
    if not isinstance(gate, dict):
        return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
    turn = gate.get("turn", {}) if isinstance(gate.get("turn", {}), dict) else {}
    value = turn.get("reclaim_grace_seconds", DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS)
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS


__all__ = [
    "DEFAULT_AGENT_AUTO_RESTART_ENABLED",
    "DEFAULT_AGENT_AUTO_RESTART_MAX_DEFER_SECONDS",
    "DEFAULT_AGENT_AUTO_RESTART_PENDING_RESURFACE_SECONDS",
    "DEFAULT_AGENT_AUTO_RESTART_QUIESCENCE_SECONDS",
    "DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_30M",
    "DEFAULT_AGENT_AUTO_RESTART_STORM_MAX_PER_EPISODE",
    "DEFAULT_AGENT_SCOPE_TEARDOWN_ENABLED",
    "DEFAULT_AGENT_SCOPE_TEARDOWN_REAPER_MIN_SCOPE_AGE_SECONDS",
    "DEFAULT_AGENT_SCOPE_TEARDOWN_SPARE_PROCESS_PATTERNS",
    "DEFAULT_AGENT_SCOPE_TEARDOWN_TERM_GRACE_SECONDS",
    "DEFAULT_DISK_PRESSURE_ERROR_FREE_PERCENT",
    "DEFAULT_DISK_PRESSURE_TOP_OWNER_MIN_BYTES",
    "DEFAULT_DISK_PRESSURE_WARN_FREE_PERCENT",
    "DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS",
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
    "get_agent_auto_restart_enabled",
    "get_agent_auto_restart_max_defer_seconds",
    "get_agent_auto_restart_pending_resurface_seconds",
    "get_agent_auto_restart_quiescence_seconds",
    "get_agent_auto_restart_storm_max_per_30m",
    "get_agent_auto_restart_storm_max_per_episode",
    "get_agent_scope_teardown_enabled",
    "get_agent_scope_teardown_reaper_min_scope_age_seconds",
    "get_agent_scope_teardown_spare_process_patterns",
    "get_agent_scope_teardown_term_grace_seconds",
    "get_disk_pressure_error_free_percent",
    "get_disk_pressure_top_owner_min_bytes",
    "get_disk_pressure_warn_free_percent",
    "get_gate_turn_reclaim_grace_seconds",
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
]
