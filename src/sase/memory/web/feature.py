"""Feature-flag helper for memory web consumers."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags


def memory_webs_enabled() -> bool:
    """Return true when the beta memory-web path is active."""

    return current_flags().enabled(FeatureFlag.memory_webs)


__all__ = ["memory_webs_enabled"]
