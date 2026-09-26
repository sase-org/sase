"""Disk-pressure, managed-tmp, and gate-shell settings accessors."""

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
DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS = 3 * 24 * 3600
DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS = 14 * 24 * 3600
DEFAULT_MANAGED_TMP_MAX_REMOVALS = 2000
DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES = 32 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES = 48 * 1024 * 1024 * 1024
DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS = 12 * 3600
DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS = 3600
DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES = 1024 * 1024 * 1024
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


def get_gate_turn_reclaim_grace_seconds() -> int:
    """Return the grace period before a missed gate-turn deadline is lost."""
    try:
        gate = _merged_config().get("gate", {})
    except Exception:  # noqa: BLE001 - maintenance cleanup should fail open.
        return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
    if not isinstance(gate, dict):
        return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
    turn = gate.get("turn", {}) if isinstance(gate.get("turn", {}), dict) else {}
    if "reclaim_grace_seconds" in turn:
        value = turn.get(
            "reclaim_grace_seconds", DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
        )
    else:
        # legacy sase-shell spelling: gate.shell.reclaim_grace_seconds reads
        # only while the sunset flag accepts retired syntax.
        from sase.agent.legacy_sase_shell_syntax import (
            _legacy_sase_shell_syntax_enabled,
        )

        shell = gate.get("shell", {})
        if (
            isinstance(shell, dict)
            and "reclaim_grace_seconds" in shell
            and _legacy_sase_shell_syntax_enabled()
        ):
            value = shell.get(
                "reclaim_grace_seconds", DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
            )
        else:
            value = DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_GATE_TURN_RECLAIM_GRACE_SECONDS


__all__ = [
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
