"""Configuration helpers for local-daemon read routing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sase.config import load_merged_config
from sase.daemon.paths import daemon_disabled

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

SURFACE_GROUP_BY_READ_SURFACE = {
    "changespec_list": "changespecs",
    "changespec_search": "changespecs",
    "changespec_detail": "changespecs",
    "agent_active": "agents",
    "agent_recent": "agents",
    "agent_archive": "agents",
    "agent_search": "agents",
    "agent_detail": "agents",
    "ace_archive_search": "ace_archive_search",
    "notification_list": "notifications",
    "notification_detail": "notifications",
    "notification_counts": "notifications",
    "notification_pending_actions": "notifications",
    "bead_list": "beads",
    "bead_ready": "beads",
    "bead_blocked": "beads",
    "bead_show": "beads",
    "bead_stats": "beads",
    "xprompt_catalog": "catalogs",
    "editor_catalog": "catalogs",
    "snippet_catalog": "catalogs",
    "file_history": "catalogs",
    "ace_agent_active": "ace_agents",
    "ace_agent_recent": "ace_agents",
    "ace_agent_archive": "ace_agents",
    "ace_agent_search": "ace_agents",
    "ace_agent_detail": "ace_agents",
    "ace_changespec_list": "ace_changespecs",
    "ace_changespec_search": "ace_changespecs",
    "ace_changespec_detail": "ace_changespecs",
    "ace_notification_list": "ace_notifications",
    "ace_notification_detail": "ace_notifications",
    "ace_notification_counts": "ace_notifications",
    "ace_notification_pending_actions": "ace_notifications",
    "ace_artifact_list": "ace_artifacts",
    "ace_artifact_detail": "ace_artifacts",
    "ace_archive": "ace_archive_search",
    "ace_search": "ace_archive_search",
}

DEFAULT_ENABLED_SURFACE_GROUPS = frozenset(
    {"changespecs", "notifications", "agents", "beads", "catalogs"}
)

ACE_DAEMON_SURFACE_GROUPS = frozenset(
    {
        "ace_agents",
        "ace_changespecs",
        "ace_notifications",
        "ace_artifacts",
        "ace_archive_search",
    }
)


@dataclass(frozen=True)
class _DaemonReadDisableReason:
    """Why a daemon read should route directly to source stores."""

    reason: str
    message: str


def daemon_read_disable_reason(
    surface: str,
    *,
    args: Any | None = None,
) -> _DaemonReadDisableReason | None:
    """Return a direct-loader reason when daemon reads are disabled."""

    if daemon_disabled(args):
        return _DaemonReadDisableReason(
            reason="daemon_disabled",
            message="daemon reads disabled by --no-daemon or SASE_NO_DAEMON",
        )
    if _daemon_read_force_direct():
        return _DaemonReadDisableReason(
            reason="force_direct",
            message="daemon reads disabled by daemon.reads.force_direct",
        )
    if not _daemon_reads_enabled():
        return _DaemonReadDisableReason(
            reason="daemon_reads_disabled",
            message="daemon reads disabled by daemon.reads.enabled",
        )
    if not daemon_read_surface_enabled(surface):
        group = _daemon_read_surface_group(surface)
        return _DaemonReadDisableReason(
            reason="surface_disabled",
            message=f"daemon reads disabled for {group}",
        )
    return None


def _daemon_reads_enabled() -> bool:
    """Return the global daemon read-through switch."""

    env_value = _optional_env_bool("SASE_DAEMON_READS")
    if env_value is not None:
        return env_value
    return _reads_bool("enabled", default=True)


def _daemon_read_force_direct() -> bool:
    """Return whether read routing should always use direct loaders."""

    env_value = _optional_env_bool("SASE_DAEMON_FORCE_DIRECT")
    if env_value is not None:
        return env_value
    return _reads_bool("force_direct", default=False)


def daemon_fallback_diagnostics_enabled() -> bool:
    """Return whether call sites should expose daemon fallback metadata."""

    env_value = _optional_env_bool("SASE_DAEMON_FALLBACK_DIAGNOSTICS")
    if env_value is not None:
        return env_value
    return _reads_bool("fallback_diagnostics", default=False)


def daemon_read_surface_enabled(surface: str) -> bool:
    """Return whether a logical read surface may use daemon projections."""

    group = _daemon_read_surface_group(surface)
    env_value = _optional_env_bool(_surface_env_name(group))
    if env_value is not None:
        return env_value
    surfaces = _reads_config().get("surfaces")
    if not isinstance(surfaces, dict):
        return group in DEFAULT_ENABLED_SURFACE_GROUPS
    value = surfaces.get(group)
    if isinstance(value, bool):
        return value
    return group in DEFAULT_ENABLED_SURFACE_GROUPS


def _daemon_read_surface_group(surface: str) -> str:
    """Return the rollout group for an individual daemon read surface."""

    return SURFACE_GROUP_BY_READ_SURFACE.get(surface, surface)


def _reads_bool(key: str, *, default: bool) -> bool:
    value = _reads_config().get(key)
    return value if isinstance(value, bool) else default


def _reads_config() -> dict[str, Any]:
    daemon_config = load_merged_config().get("daemon")
    if not isinstance(daemon_config, dict):
        return {}
    reads_config = daemon_config.get("reads")
    return reads_config if isinstance(reads_config, dict) else {}


def _optional_env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _surface_env_name(group: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in group.upper())
    return f"SASE_DAEMON_{token}_READS"


__all__ = [
    "ACE_DAEMON_SURFACE_GROUPS",
    "DEFAULT_ENABLED_SURFACE_GROUPS",
    "SURFACE_GROUP_BY_READ_SURFACE",
    "daemon_fallback_diagnostics_enabled",
    "daemon_read_disable_reason",
    "daemon_read_surface_enabled",
]
