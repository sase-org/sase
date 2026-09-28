"""Feature-flag helper for the ToolRun TUI surfaces (epic sase-1bt)."""

from __future__ import annotations


def tool_runs_enabled() -> bool:
    """Return True while the ``ace_tool_runs`` beta flag is on."""
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.ace_tool_runs)


__all__ = ["tool_runs_enabled"]
