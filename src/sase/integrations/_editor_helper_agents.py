"""Read-only agent catalog for editor completion clients."""

from __future__ import annotations

from typing import Any


def agent_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    """Return a fresh, de-duplicated catalog of prompt-referenceable agents."""
    if request.get("schema_version") != 1:
        raise ValueError("unsupported agent-catalog schema_version")

    from sase.agent.running_listing import list_all_agents
    from sase.project_display_names import project_display_name_for

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for agent in list_all_agents():
        name = (agent.name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append(
            {
                "name": name,
                "status": agent.status,
                "project": project_display_name_for(agent.project),
            }
        )

    return {
        "schema_version": 1,
        "status": "ok",
        "message": "",
        "entries": entries,
    }


__all__ = ["agent_catalog_response"]
