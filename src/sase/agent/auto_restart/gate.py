"""Feature enablement for update-skew auto-restart.

The ``agent_auto_restart.enabled`` config field is the permanent kill switch:
automatic paths act only while it is on. With it off, the healer and the
scheduler job re-surface pending failures loudly and never write the ledger.
(The land phase of epic sase-1j6 removed the beta flag; no flag gates this
feature anymore.)
"""

from __future__ import annotations


def auto_restart_automatic_enabled() -> bool:
    """Return whether any automatic auto-restart path may act."""
    try:
        from sase.config._settings_system import get_agent_auto_restart_enabled

        return bool(get_agent_auto_restart_enabled())
    except Exception:
        return False


__all__ = ["auto_restart_automatic_enabled"]
