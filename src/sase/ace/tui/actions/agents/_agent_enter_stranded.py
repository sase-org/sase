"""Stranded Enter-target builder and list insertion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.bead.stranded_presentation import STRANDED_GLYPH, STRANDED_LEAF_STYLE

from ._agent_enter_models import AgentEnterTarget, identity_of

if TYPE_CHECKING:
    from ...models import Agent


def _stranded_enter_target(agent: Agent) -> AgentEnterTarget | None:
    """Return a ``stranded`` Enter target for *agent*, or ``None``."""
    from ...models.agent_stranded import (
        agent_stranded_view,
        cached_stranded_report,
        stranded_project_key_for_agent,
    )

    view = agent_stranded_view(agent)
    project = stranded_project_key_for_agent(agent)
    bead_id: str | None = None
    if view.verdict is not None and view.verdict.state in {"stranded", "blocked"}:
        bead_id = view.verdict.bead_id
    elif view.waiting_on:
        bead_id = view.waiting_on[0][0]
    elif view.waiting_on_agents:
        bead_id = view.waiting_on_agents[0][0]
    elif view.clan_stranded_ids:
        if project is None:
            from ...models._agent_clan import clan_members

            for member in clan_members(agent):
                project = stranded_project_key_for_agent(member)
                if project is not None:
                    break
        epic_id = getattr(agent, "agent_clan", None) or getattr(
            agent, "presented_agent_name", None
        )
        epic_verdict = None
        if project is not None and isinstance(epic_id, str) and epic_id.strip():
            snapshot = cached_stranded_report(project)
            if snapshot is not None:
                epic_verdict = next(
                    (
                        item
                        for item in snapshot.report.verdicts
                        if item.bead_id == epic_id
                    ),
                    None,
                )
        if epic_verdict is not None and epic_verdict.state in {"stranded", "blocked"}:
            bead_id = epic_verdict.bead_id
        else:
            bead_id = view.clan_stranded_ids[0]
    if bead_id is None or project is None:
        return None
    return AgentEnterTarget(
        kind="stranded",
        source="stranded",
        key=f"stranded:{project}:{bead_id}",
        label="resolve stranded",
        detail=bead_id,
        badge=STRANDED_GLYPH,
        badge_style=STRANDED_LEAF_STYLE,
        bead_id=bead_id,
        project_key=project,
        row_identity=identity_of(agent),
    )


def append_stranded_target(targets: list[AgentEnterTarget], agent: Agent) -> None:
    """Insert a stranded target after gates and before a trailing Patch."""
    stranded = _stranded_enter_target(agent)
    if stranded is None or any(item.kind == "stranded" for item in targets):
        return
    if targets and targets[-1].kind == "patch":
        targets.insert(-1, stranded)
    else:
        targets.append(stranded)


__all__ = ["append_stranded_target"]
