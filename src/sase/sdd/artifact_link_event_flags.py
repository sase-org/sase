"""Feature-gate helpers for artifact-link event publication."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags


def artifact_link_events_enabled() -> bool:
    """Return whether artifact-link writers should use immutable link events."""

    return current_flags().enabled(FeatureFlag.link_events)


__all__ = ["artifact_link_events_enabled"]
