"""Remote fleet provenance fields for the agent detail header."""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text

from ...models.agent import Agent


def append_fleet_fields(text: Text, agent: Agent) -> None:
    """Append remote fleet provenance for read-only projected rows."""
    if not agent.fleet_origin_alias:
        return
    text.append("Machine: ", style="bold #87D7FF")
    text.append(agent.fleet_origin_alias, style="bold #5FD7FF")
    text.append("\n")

    fields = [
        field
        for field in (
            agent.fleet_connection_health,
            agent.fleet_freshness,
            agent.fleet_bounded_intent,
        )
        if field
    ]
    if agent.fleet_revision is not None:
        fields.append(f"rev {agent.fleet_revision}")
    if fields:
        text.append("Remote: ", style="bold #87D7FF")
        text.append(" · ".join(dict.fromkeys(fields)), style="#87D7D7")
        text.append("\n")
    if agent.fleet_diagnostic:
        text.append("Feed error: ", style="bold #FF8700")
        text.append(agent.fleet_diagnostic, style="#FFAF5F")
        text.append("\n")
    _append_remote_action_fields(text, agent)


def _append_remote_action_fields(text: Text, agent: Agent) -> None:
    available, unavailable = _remote_action_summaries(agent)
    if not available and not unavailable:
        return
    text.append("Remote actions: ", style="bold #87D7FF")
    if available:
        text.append(" · ".join(available), style="#5FD7AF")
    if unavailable:
        if available:
            text.append(" ")
        text.append("(unavailable: ", style="dim")
        text.append(" · ".join(unavailable), style="dim #D7AF87")
        text.append(")", style="dim")
    text.append("\n")


def _remote_action_summaries(agent: Agent) -> tuple[list[str], list[str]]:
    from ...actions.agents._remote_attention import has_pending_remote_attention
    from ...actions.agents._remote_content import (
        remote_content_available,
    )
    from ...actions.agents._remote_lifecycle import remote_capability_enabled

    available: list[str] = []
    unavailable: list[str] = []

    for label, capability in (
        ("stop", "lifecycle.stop"),
        ("retry", "lifecycle.retry"),
        ("fork", "lifecycle.fork"),
    ):
        if remote_capability_enabled(agent, capability):
            available.append(label)
        else:
            unavailable.append(f"{label} not advertised")

    if remote_content_available(agent):
        available.append("content")
    else:
        content = (
            agent.fleet_content if isinstance(agent.fleet_content, Mapping) else {}
        )
        raw_handles = content.get("handles") or content.get("content_handles")
        if raw_handles:
            unavailable.append("content missing row revision")
        else:
            unavailable.append("content no handle")

    if has_pending_remote_attention(agent):
        attention = (
            agent.fleet_attention if isinstance(agent.fleet_attention, Mapping) else {}
        )
        kind = str(attention.get("kind") or "attention")
        available.append("approve" if kind == "gate" else "answer")
    else:
        attention = (
            agent.fleet_attention if isinstance(agent.fleet_attention, Mapping) else {}
        )
        if attention.get("state") == "pending":
            unavailable.append("attention not advertised")
        else:
            unavailable.append("attention no pending request")

    return available, unavailable
