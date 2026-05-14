"""Configuration helpers for daemon scheduler launch routing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from sase.config import load_merged_config
from sase.daemon.paths import daemon_disabled

SchedulerLaunchMode = Literal["direct", "shadow", "daemon"]

_ENV_MODE = "SASE_DAEMON_SCHEDULER_LAUNCH_MODE"
_LEGACY_ENV_MODE = "SASE_SCHEDULER_LAUNCH_MODE"
_MODE_ALIASES: dict[str, SchedulerLaunchMode] = {
    "off": "direct",
    "false": "direct",
    "0": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "daemon": "daemon",
    "daemon_authoritative": "daemon",
    "authoritative": "daemon",
    "on": "daemon",
    "true": "daemon",
    "1": "daemon",
}


@dataclass(frozen=True)
class _SchedulerLaunchDisableReason:
    """Why a launch should use the direct Python launcher."""

    reason: str
    message: str


def scheduler_launch_mode() -> SchedulerLaunchMode:
    """Return the configured daemon scheduler launch rollout mode."""

    env_value = os.environ.get(_ENV_MODE) or os.environ.get(_LEGACY_ENV_MODE)
    parsed = _parse_mode(env_value)
    if parsed is not None:
        return parsed

    daemon_config = load_merged_config().get("daemon")
    scheduler_config = (
        daemon_config.get("scheduler") if isinstance(daemon_config, dict) else None
    )
    if not isinstance(scheduler_config, dict):
        return "direct"
    parsed = _parse_mode(scheduler_config.get("launch_mode"))
    return parsed or "direct"


def scheduler_launch_disable_reason(
    args: object | None = None,
) -> _SchedulerLaunchDisableReason | None:
    """Return a direct-launch reason when scheduler routing is disabled."""

    if daemon_disabled(args):
        return _SchedulerLaunchDisableReason(
            reason="daemon_disabled",
            message="daemon scheduler launches disabled by --no-daemon or SASE_NO_DAEMON",
        )
    if os.environ.get("SASE_DAEMON_SCHEDULER_HOST_BRIDGE") == "1":
        return _SchedulerLaunchDisableReason(
            reason="host_bridge",
            message="scheduler host bridge must execute launches directly",
        )
    if scheduler_launch_mode() == "direct":
        return _SchedulerLaunchDisableReason(
            reason="direct_mode",
            message="daemon scheduler launches disabled by daemon.scheduler.launch_mode",
        )
    return None


def _parse_mode(value: object) -> SchedulerLaunchMode | None:
    if not isinstance(value, str):
        return None
    return _MODE_ALIASES.get(value.strip().lower().replace("-", "_"))


__all__ = [
    "SchedulerLaunchMode",
    "scheduler_launch_disable_reason",
    "scheduler_launch_mode",
]
