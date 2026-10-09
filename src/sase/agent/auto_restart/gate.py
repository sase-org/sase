"""Feature enablement for update-skew auto-restart.

Both the ``agent_auto_restart`` beta flag and the ``agent_auto_restart.enabled``
config field must agree before any automatic path acts. With either off, the
healer and the scheduler job re-surface pending failures loudly and never
write the ledger. The config field is the permanent kill switch; the flag is
epic scaffolding removed by the land phase.
"""

from __future__ import annotations


def auto_restart_automatic_enabled() -> bool:
    """Return whether any automatic auto-restart path may act."""
    try:
        from sase.config._settings_system import get_agent_auto_restart_enabled

        if not get_agent_auto_restart_enabled():
            return False
    except Exception:
        return False
    try:
        from sase.feature_flags import FeatureFlag, current_flags

        return bool(current_flags().enabled(FeatureFlag.agent_auto_restart))
    except Exception:
        return False


__all__ = ["auto_restart_automatic_enabled"]
