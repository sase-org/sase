"""Environment and feature-flag checks for ACE data providers."""

from __future__ import annotations

import os

from sase.daemon.read_config import daemon_read_surface_enabled


def agents_daemon_reads_enabled() -> bool:
    """Return whether ACE should try daemon-backed Agents-tab reads."""

    value = os.environ.get("SASE_ACE_AGENTS_DAEMON_READS", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return daemon_read_surface_enabled("ace_agents")


def ace_archive_search_daemon_reads_enabled() -> bool:
    """Return whether ACE archive/search agent reads may use daemon pages."""

    value = os.environ.get("SASE_ACE_ARCHIVE_SEARCH_DAEMON_READS", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return daemon_read_surface_enabled("ace_archive_search")
