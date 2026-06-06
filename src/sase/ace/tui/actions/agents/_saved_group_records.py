"""Helpers for saved dismissed-agent group records."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupWire,
)

if TYPE_CHECKING:
    from ...models import Agent

SavedAgentGroupSource = Literal["marked_agents", "recent_dismissal"]


def utc_wire_timestamp(value: datetime) -> str:
    """Return a UTC ISO timestamp using the archive wire's ``Z`` convention."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def plural_agent(count: int) -> str:
    return "agent" if count == 1 else "agents"


def build_saved_agent_group(
    agents: list[Agent],
    *,
    group_name: str | None = None,
    source: SavedAgentGroupSource = "marked_agents",
    created_at: datetime | None = None,
) -> SavedAgentGroupWire:
    """Build a saved-group wire record from concrete agent rows."""

    now = created_at or datetime.now(UTC)
    created_at_wire = utc_wire_timestamp(now)
    status_counts = dict(sorted(Counter(a.status for a in agents if a.status).items()))
    project_names = tuple(
        sorted({name for a in agents if (name := _agent_project_name(a)) is not None})
    )
    cl_names = tuple(
        sorted({a.cl_name for a in agents if a.cl_name and a.cl_name != "unknown"})
    )
    top_level_count = sum(1 for agent in agents if not agent.is_workflow_child)
    return SavedAgentGroupWire(
        group_id=_saved_group_id(agents, source=source, created_at=now),
        created_at=created_at_wire,
        source=source,
        title=_saved_group_title(agents),
        name=_normalize_saved_group_name(group_name),
        agent_count=len(agents),
        top_level_agent_count=top_level_count,
        status_counts=status_counts,
        project_names=project_names,
        cl_names=cl_names,
        agent_refs=tuple(_saved_group_ref_for_agent(agent) for agent in agents),
    )


def normalize_saved_group_name(group_name: str | None) -> str | None:
    return _normalize_saved_group_name(group_name)


def _saved_group_id(
    agents: list[Agent],
    *,
    source: SavedAgentGroupSource,
    created_at: datetime,
) -> str:
    timestamp = created_at.strftime("%Y%m%dT%H%M%S%fZ")
    if source == "recent_dismissal":
        digest = _agent_identity_digest(agents)
        return f"recent-{timestamp}-{digest}"
    return f"marked-{timestamp}"


def _agent_identity_digest(agents: list[Agent]) -> str:
    hasher = hashlib.blake2s(digest_size=6)
    for agent in agents:
        hasher.update(agent.agent_type.value.encode("utf-8", errors="replace"))
        hasher.update(b"\0")
        hasher.update(agent.cl_name.encode("utf-8", errors="replace"))
        hasher.update(b"\0")
        hasher.update((agent.raw_suffix or "").encode("utf-8", errors="replace"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _agent_start_time_wire(agent: Agent) -> str | None:
    if agent.start_time is None:
        return None
    if agent.start_time.tzinfo is None:
        return agent.start_time.isoformat()
    return utc_wire_timestamp(agent.start_time)


def _agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    parent = Path(agent.project_file).parent.name
    if parent:
        return parent
    stem = Path(agent.project_file).stem
    return stem or None


def _saved_group_title(agents: list[Agent]) -> str:
    count = len(agents)
    tags = sorted({a.tag for a in agents if a.tag})
    cl_names = sorted(
        {a.cl_name for a in agents if a.cl_name and a.cl_name != "unknown"}
    )
    project_names = sorted(
        {name for a in agents if (name := _agent_project_name(a)) is not None}
    )

    if len(tags) == 1:
        return f"{count} {plural_agent(count)} from @{tags[0]}"
    if len(cl_names) == 1:
        return f"{count} {plural_agent(count)} in {cl_names[0]}"
    if len(project_names) == 1:
        return f"{count} {plural_agent(count)} from {project_names[0]}"
    if len(cl_names) > 1:
        return f"{count} {plural_agent(count)} across {len(cl_names)} CLs"
    return f"{count} {plural_agent(count)}"


def _normalize_saved_group_name(group_name: str | None) -> str | None:
    if group_name is None:
        return None
    normalized = group_name.strip()
    return normalized or None


def _bundle_path_for_agent(agent: Agent) -> str | None:
    existing = getattr(agent, "_dismissed_bundle_path", None)
    if existing:
        return existing
    if agent.raw_suffix is None:
        return None
    try:
        from ....dismissed_agents import dismissed_bundle_path_for_agent

        path = dismissed_bundle_path_for_agent(agent)
    except Exception:
        return None
    return None if path is None else str(path)


def _saved_group_ref_for_agent(agent: Agent) -> SavedAgentGroupRefWire:
    return SavedAgentGroupRefWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
        bundle_path=_bundle_path_for_agent(agent),
        is_workflow_child=agent.is_workflow_child,
        parent_timestamp=agent.parent_timestamp,
        display_name=agent.display_name,
        agent_name=agent.agent_name,
        status=agent.status,
        start_time=_agent_start_time_wire(agent),
        model=agent.model,
        llm_provider=agent.llm_provider,
        tag=agent.tag,
    )
