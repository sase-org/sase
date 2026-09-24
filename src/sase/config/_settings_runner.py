"""Runner, agent-hold, and proc-history settings accessors."""

from __future__ import annotations

from typing import Any

from sase.config import _settings as _settings_facade


def _merged_config() -> dict[str, Any]:
    """Route through the facade so its patch point stays effective."""
    return _settings_facade.merged_config()


DEFAULT_MAX_RUNNING_AGENTS = 10
DEFAULT_MAX_AGENT_PIPE_CHAIN = 8
DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP = 3
DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS = 60
DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS = 2 * 3600.0
DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS = 12 * 3600.0
DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD = 10
DEFAULT_PROC_HISTORY_LIMIT = 100
DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS = 3 * 24 * 3600
DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS = 2000


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
    """Return the configured ``sase pipe`` agent-session-chain bound.

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


def _get_agent_hold_ttl_seconds(key: str, default_seconds: float) -> float:
    """Parse a `agent_hold_*_ttl` config string, falling back on any error.

    A hand-edited config must never turn `sase agent hold create` into a
    traceback, so a missing, non-string, or unparsable value silently keeps
    the package default rather than propagating.
    """
    from sase.core.cli_duration import parse_cli_duration

    value = _merged_config().get(key, None)
    if not isinstance(value, str):
        return default_seconds
    try:
        seconds = parse_cli_duration(value, flag=key)[0]
    except ValueError:
        return default_seconds
    return seconds


def get_agent_hold_default_ttl_seconds() -> float:
    """Return the configured default TTL for `sase agent hold create`/`run`."""
    return _get_agent_hold_ttl_seconds(
        "agent_hold_default_ttl", DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS
    )


def get_agent_hold_max_ttl_seconds() -> float:
    """Return the configured maximum TTL accepted for an explicit --ttl."""
    return _get_agent_hold_ttl_seconds(
        "agent_hold_max_ttl", DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS
    )


def get_agent_hold_confirm_capture_threshold() -> int:
    """Return the pending-capture count above which a hold needs confirmation."""
    value = _merged_config().get(
        "agent_hold_confirm_capture_threshold",
        DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD


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


__all__ = [
    "DEFAULT_AGENT_HOLD_CONFIRM_CAPTURE_THRESHOLD",
    "DEFAULT_AGENT_HOLD_DEFAULT_TTL_SECONDS",
    "DEFAULT_AGENT_HOLD_MAX_TTL_SECONDS",
    "DEFAULT_MAX_AGENT_PIPE_CHAIN",
    "DEFAULT_MAX_RUNNING_AGENTS",
    "DEFAULT_PROC_HISTORY_LIMIT",
    "DEFAULT_PROC_RUNTIME_ORPHAN_HORIZON_SECONDS",
    "DEFAULT_PROC_RUNTIME_ORPHAN_MAX_REMOVALS",
    "DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS",
    "DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP",
    "get_agent_hold_confirm_capture_threshold",
    "get_agent_hold_default_ttl_seconds",
    "get_agent_hold_max_ttl_seconds",
    "get_configured_max_running_agents",
    "get_max_agent_pipe_chain",
    "get_proc_history_limit",
    "get_proc_runtime_orphan_horizon_seconds",
    "get_proc_runtime_orphan_max_removals",
    "get_runner_slot_deference_max_seconds",
    "get_runner_slot_deference_seconds_per_step",
    "get_use_chezmoi",
]
