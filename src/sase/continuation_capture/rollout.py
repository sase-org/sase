"""Feature-flag guard for the monitor continuation record rollout."""

from __future__ import annotations


def monitor_continuation_records_enabled() -> bool:
    """Return whether new monitor runs should use versioned continuation records."""

    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.monitor_continuation_records)


__all__ = ["monitor_continuation_records_enabled"]
