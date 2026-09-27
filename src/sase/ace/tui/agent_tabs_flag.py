"""Feature-flag helper for the agent-tabs beta (epic sase-1bc)."""

from __future__ import annotations


def agent_tabs_enabled() -> bool:
    """Return True while the ``agent_tabs`` beta flag is on."""
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.agent_tabs)


__all__ = ["agent_tabs_enabled"]
