"""Presentation landing for successful stopped-agent navigation."""

from __future__ import annotations

from typing import Any


def land_stopped_jump_on_main_context(app: Any) -> None:
    """Focus Main and request a Context landing for the selected stopped agent."""
    try:
        if app.current_tab != "agents" or app._current_group_key is not None:
            return
        agent = app._agents[app.current_idx]
    except Exception:
        return

    try:
        from ...widgets import AgentDetail

        detail = app.query_one("#agent-detail-panel", AgentDetail)
    except Exception:
        return
    try:
        detail.request_main_context_landing(agent.identity)
    except Exception:
        return
    try:
        refresh = getattr(app, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh):
            refresh()
    except Exception:
        pass


__all__ = ["land_stopped_jump_on_main_context"]
