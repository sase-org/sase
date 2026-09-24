"""Agent decks beta flag access for deck widgets."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags


def agent_decks_enabled() -> bool:
    """Return whether the agent decks beta flag is on."""
    return bool(current_flags().enabled(FeatureFlag.agent_decks))


def agent_decks_active(app: object) -> bool:
    """Return whether the mounted AgentDetail has decks enabled."""
    try:
        from ..agent_detail import AgentDetail

        detail = app.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
    except Exception:
        return False
    try:
        return bool(detail.decks_enabled)
    except Exception:
        return False
