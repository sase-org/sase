"""Validated accessors for individual values held in the merged config.

Each accessor projects one merged-config value into a typed Python result and
falls back to the package default when the value is missing or malformed: a
hand-edited ``~/.config/sase/sase.yml`` must never turn a routine command into
a traceback.  Accessors that run on formatting or scheduling paths widen that
to catching load failures outright, which each one notes.

Reads go through :mod:`sase.config.core` rather than binding
``load_merged_config`` at import time so the facade keeps owning the cache and
remains the single patch point every accessor here honors.
"""

from __future__ import annotations

from typing import Any

from sase.markdown_width import DEFAULT_MARKDOWN_PRINT_WIDTH
from sase.markdown_wrap import MIN_PROSE_WRAP_WIDTH


DEFAULT_MAX_RUNNING_AGENTS = 10
DEFAULT_MAX_AGENT_PIPE_CHAIN = 8
DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP = 3
DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS = 60
DEFAULT_PROC_HISTORY_LIMIT = 100
DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS = 3 * 24 * 3600
DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS = 2000
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
DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES = 1024 * 1024 * 1024
DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS = 3600
DEFAULT_PAGER_SYNTAX = "auto"
DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES = 8 * 1024
DEFAULT_MONITOR_FALLBACK_TAIL_BYTES = 4 * 1024
DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES = 12 * 1024
DEFAULT_MONITOR_RAW_TAIL_LINES = 200


def _merged_config() -> dict[str, Any]:
    """Return the effective config through the ``sase.config.core`` facade.

    The import is deferred because ``core`` imports this module at load time.
    """
    from sase.config.core import load_merged_config

    return load_merged_config()


def get_use_chezmoi() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    return bool(_merged_config().get("use_chezmoi", False))


def get_configured_max_running_agents() -> int:
    """Return the validated configured global runner limit.

    The merged-config cache lets admission callers poll this accessor without
    reparsing unchanged YAML while still observing live edits.
    """
    value = _merged_config().get("max_running_agents", DEFAULT_MAX_RUNNING_AGENTS)
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MAX_RUNNING_AGENTS


def get_max_agent_pipe_chain() -> int:
    """Return the configured ``sase pipe`` family-chain bound.

    The original agent is depth 0. A pipe is refused when the next link
    would exceed this value. Malformed configuration falls back to the
    package default rather than allowing an unbounded chain.
    """
    value = _merged_config().get("max_agent_pipe_chain", DEFAULT_MAX_AGENT_PIPE_CHAIN)
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MAX_AGENT_PIPE_CHAIN


def get_runner_slot_deference_seconds_per_step() -> int:
    """Return the configured per-priority-step delay, falling back on errors.

    Unlike the effective runner limit, deference is a politeness optimization:
    malformed or unavailable configuration must never strand a runner.
    """
    try:
        runner_slots = _merged_config().get("runner_slots", {})
    except Exception:  # noqa: BLE001 - deference configuration is fail-open.
        return DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP
    value = (
        runner_slots.get(
            "deference_seconds_per_step",
            DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP,
        )
        if isinstance(runner_slots, dict)
        else DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP


def get_runner_slot_deference_max_seconds() -> int:
    """Return the configured deference cap, falling back on errors.

    Unlike the effective runner limit, deference is a politeness optimization:
    malformed or unavailable configuration must never strand a runner.
    """
    try:
        runner_slots = _merged_config().get("runner_slots", {})
    except Exception:  # noqa: BLE001 - deference configuration is fail-open.
        return DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS
    value = (
        runner_slots.get(
            "deference_max_seconds",
            DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS,
        )
        if isinstance(runner_slots, dict)
        else DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS


def get_proc_history_limit() -> int:
    """Return the validated configured finished-proc retention limit."""
    merged = _merged_config()
    procs = merged.get("procs", {})
    if isinstance(procs, dict) and "history_limit" in procs:
        value = procs["history_limit"]
    else:
        tasks = merged.get("tasks", {})
        value = (
            tasks.get("history_limit", DEFAULT_PROC_HISTORY_LIMIT)
            if isinstance(tasks, dict)
            else DEFAULT_PROC_HISTORY_LIMIT
        )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_PROC_HISTORY_LIMIT


def _procs_config() -> dict[str, Any]:
    value = _merged_config().get("procs", {})
    if isinstance(value, dict):
        return value
    tasks = _merged_config().get("tasks", {})
    return tasks if isinstance(tasks, dict) else {}


def get_proc_runtime_orphan_horizon_seconds() -> float:
    """Return the age horizon for rowless proc runtime directories."""
    value = _procs_config().get(
        "runtime_orphan_horizon_seconds",
        DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS,
    )
    if type(value) in {int, float} and value >= 0:
        return float(value)
    return float(DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS)


def get_proc_runtime_orphan_max_removals() -> int:
    """Return the per-pass budget for historical proc runtime orphans."""
    value = _procs_config().get(
        "runtime_orphan_max_removals",
        DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS


# Legacy accessor alias; retire after every caller moves to the proc spelling.
get_task_history_limit = get_proc_history_limit


def get_pager_syntax() -> str:
    """Return ``pager.syntax``: ``auto`` or ``never``.

    Unknown or malformed values fall back to ``auto`` so a hand-edited
    ``sase.yml`` cannot crash the pager. Schema validation is the diagnostic
    path for rejected values.
    """
    try:
        pager = _merged_config().get("pager", {})
    except Exception:  # noqa: BLE001 - pager syntax is fail-open.
        return DEFAULT_PAGER_SYNTAX
    value = (
        pager.get("syntax", DEFAULT_PAGER_SYNTAX)
        if isinstance(pager, dict)
        else DEFAULT_PAGER_SYNTAX
    )
    if value in {"auto", "never"}:
        return str(value)
    return DEFAULT_PAGER_SYNTAX


def get_monitor_evidence_limits() -> dict[str, int]:
    """Return validated monitor evidence projection byte and line limits."""
    try:
        monitor = _merged_config().get("monitor", {})
    except Exception:  # noqa: BLE001 - evidence projection should fail open.
        return _default_monitor_evidence_limits()
    evidence = monitor.get("evidence_limits", {}) if isinstance(monitor, dict) else {}
    config = evidence if isinstance(evidence, dict) else {}
    limits = {
        "selected_diagnostics_bytes": _positive_int_config(
            config,
            "selected_diagnostics_bytes",
            DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
        ),
        "fallback_tail_bytes": _positive_int_config(
            config,
            "fallback_tail_bytes",
            DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
        ),
        "total_raw_excerpt_bytes": _positive_int_config(
            config,
            "total_raw_excerpt_bytes",
            DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
        ),
        "raw_tail_lines": _positive_int_config(
            config,
            "raw_tail_lines",
            DEFAULT_MONITOR_RAW_TAIL_LINES,
        ),
    }
    if (
        limits["selected_diagnostics_bytes"] > limits["total_raw_excerpt_bytes"]
        or limits["fallback_tail_bytes"] > limits["total_raw_excerpt_bytes"]
    ):
        return _default_monitor_evidence_limits()
    return limits


def _default_monitor_evidence_limits() -> dict[str, int]:
    return {
        "selected_diagnostics_bytes": DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
        "fallback_tail_bytes": DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
        "total_raw_excerpt_bytes": DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
        "raw_tail_lines": DEFAULT_MONITOR_RAW_TAIL_LINES,
    }


def _positive_int_config(
    config: dict[str, Any],
    key: str,
    default: int,
) -> int:
    value = config.get(key, default)
    return value if type(value) is int and value >= 1 else default


def get_markdown_print_width() -> int:
    """Return the validated configured Markdown prose width.

    Formatting must never hard-fail: a malformed ``~/.config/sase/sase.yml``
    turning ``sase plan propose`` into a traceback would be far worse than
    wrapping at the shipped default, so this accessor is fail-open.
    """
    try:
        markdown = _merged_config().get("markdown", {})
    except Exception:  # noqa: BLE001 - prose width is fail-open.
        return DEFAULT_MARKDOWN_PRINT_WIDTH
    value = (
        markdown.get("print_width", DEFAULT_MARKDOWN_PRINT_WIDTH)
        if isinstance(markdown, dict)
        else DEFAULT_MARKDOWN_PRINT_WIDTH
    )
    # Below ``MIN_PROSE_WRAP_WIDTH`` ``wrap_markdown()`` silently returns text
    # unwrapped, so the floor is the schema's ``minimum`` too.
    if type(value) is int and value >= MIN_PROSE_WRAP_WIDTH:
        return value
    return DEFAULT_MARKDOWN_PRINT_WIDTH


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


def get_managed_tmp_pressure_min_entry_bytes() -> int:
    """Return the minimum entry size that participates in pressure pruning."""
    value = _managed_tmp_pressure_config().get(
        "min_entry_bytes",
        DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES


def get_gate_shell_reclaim_grace_seconds() -> int:
    """Return the grace period before a missed gate-shell deadline is lost."""
    try:
        gate = _merged_config().get("gate", {})
    except Exception:  # noqa: BLE001 - maintenance cleanup should fail open.
        return DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
    shell = gate.get("shell", {}) if isinstance(gate, dict) else {}
    value = (
        shell.get(
            "reclaim_grace_seconds",
            DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS,
        )
        if isinstance(shell, dict)
        else DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
