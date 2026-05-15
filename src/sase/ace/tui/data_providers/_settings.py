"""Environment and feature-flag checks for ACE data providers."""

from __future__ import annotations


def agents_daemon_reads_enabled() -> bool:
    """Return whether ACE should try daemon-backed Agents-tab reads."""
    return False
