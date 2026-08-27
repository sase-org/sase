"""Feature-flag gate for the ACE link rail surface."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags


def link_rail_enabled() -> bool:
    """Return the process-local ``link_rail`` flag decision."""

    return current_flags().enabled(FeatureFlag.link_rail)


__all__ = ["link_rail_enabled"]
