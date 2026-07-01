"""Plugin-presence helpers for the Agents onboarding panel."""

from __future__ import annotations

from sase.plugins.installed import any_plugins_installed


def discover_agents_onboarding_plugins_installed() -> bool:
    """Return whether any local third-party SASE plugin is installed."""
    return any_plugins_installed()
