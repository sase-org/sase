"""Pure presentation snapshots for collapsed Agents-tab panels."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.agent.status_buckets import status_bucket_for_values
from ._agent_parallel_family import agent_summary_status_counts
from .agent import Agent, AgentType, compute_row_runtime
from .agent_panels import PanelKey


AgentIdentity = tuple[AgentType, str, str | None]


@dataclass(frozen=True, slots=True)
class CollapsedAgentPanelFocus:
    """Identity of the whole collapsed panel that currently owns focus."""

    panel_key: PanelKey


@dataclass(frozen=True, slots=True)
class _AgentPanelSummaryCounts:
    """Status projection shared with an Agents panel's title count chip."""

    stopped: int = 0
    running: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class AgentPanelSummaryRow:
    """Immutable display data for one member of a collapsed panel."""

    identity: AgentIdentity
    display_name: str
    display_status: str
    status_bucket: str
    roster_bucket: str
    depth: int
    context: tuple[str, ...]
    model: str | None
    time_label: str | None
    is_marked: bool
    is_unread: bool


@dataclass(frozen=True, slots=True)
class AgentPanelSummarySnapshot:
    """Complete, immutable collapsed-panel presentation state."""

    panel_key: PanelKey
    label: str
    entry_count: int
    root_count: int
    nested_count: int
    counts: _AgentPanelSummaryCounts
    rows: tuple[AgentPanelSummaryRow, ...]


_ROSTER_BUCKET_ORDER: dict[str, int] = {
    "Stopped": 0,
    "Failed": 1,
    "Starting": 2,
    "Running": 2,
    "Waiting": 3,
    "Unread": 4,
    "Done": 5,
}


def _collapsed_agent_panel_label(panel_key: PanelKey) -> str:
    """Return the same visible label used by an Agents panel title."""
    return "(untagged)" if panel_key is None else f"@{panel_key}"


def _row_roster_bucket(agent: Agent, unread_ids: Collection[AgentIdentity]) -> str:
    bucket = status_bucket_for_values(agent.status, agent.retried_as_timestamp)
    if bucket == "Done" and agent.identity in unread_ids:
        return "Unread"
    return bucket


def _root_for_agent(agent: Agent, by_suffix: dict[str, Agent]) -> Agent | None:
    """Resolve the available top-level ancestor of ``agent`` without I/O."""
    current = agent
    seen: set[int] = set()
    while current.is_child_row and current.parent_timestamp:
        current_id = id(current)
        if current_id in seen:
            return None
        seen.add(current_id)
        parent = by_suffix.get(current.parent_timestamp)
        if parent is None:
            return None
        current = parent
    return current if not current.is_child_row else None


def _row_depth(agent: Agent, by_suffix: dict[str, Agent]) -> int:
    """Return the nesting depth represented by already-loaded parent links."""
    if not agent.is_child_row:
        return 0
    depth = 1
    current = agent
    seen: set[int] = set()
    while current.parent_timestamp:
        current_id = id(current)
        if current_id in seen:
            break
        seen.add(current_id)
        parent = by_suffix.get(current.parent_timestamp)
        if parent is None or not parent.is_child_row:
            break
        depth += 1
        current = parent
    return depth


def _ordered_roster_agents(
    agents: Sequence[Agent],
    unread_ids: Collection[AgentIdentity],
) -> list[tuple[Agent, Agent]]:
    """Order root blocks by operational priority and keep children nested.

    The returned pair is ``(agent, block_root)``. Stable panel order is
    retained within each bucket, and every child stays in its root's block even
    when its own exact status differs from the root's projected status.
    """
    by_suffix = {agent.raw_suffix: agent for agent in agents if agent.raw_suffix}
    blocks: list[tuple[Agent, list[Agent]]] = []
    block_by_root_id: dict[int, list[Agent]] = {}

    for agent in agents:
        if agent.is_child_row:
            continue
        root_block: list[Agent] = []
        block_by_root_id[id(agent)] = root_block
        blocks.append((agent, root_block))

    for agent in agents:
        root = _root_for_agent(agent, by_suffix)
        if root is None:
            root = agent
        block = block_by_root_id.get(id(root))
        if block is None:
            block = []
            block_by_root_id[id(root)] = block
            blocks.append((root, block))
        block.append(agent)

    ordered_blocks = sorted(
        enumerate(blocks),
        key=lambda item: (
            _ROSTER_BUCKET_ORDER.get(
                _row_roster_bucket(item[1][0], unread_ids),
                len(_ROSTER_BUCKET_ORDER),
            ),
            item[0],
        ),
    )
    return [
        (agent, root)
        for _position, (root, members) in ordered_blocks
        for agent in members
    ]


def _loaded_display_name(agent: Agent) -> str:
    """Project an agent name using only metadata already on the row."""
    if (
        agent.agent_type == AgentType.WORKFLOW
        and not agent.appears_as_agent
        and not agent.is_workflow_child
        and agent.workflow
    ):
        return agent.workflow
    if agent.is_project_agent and agent.project_display_name:
        return agent.project_display_name
    if agent.project_display_name and agent.project_file:
        project_key = Path(agent.project_file).parent.name
        prefix = f"{project_key}_"
        if agent.cl_name.startswith(prefix):
            return f"{agent.project_display_name}_{agent.cl_name[len(prefix) :]}"
    return agent.cl_name


def _agent_context(agent: Agent, display_name: str) -> tuple[str, ...]:
    """Return useful project / ChangeSpec context without placeholders."""
    project = (agent.project_display_name or "").strip()
    project_key = ""
    if not project and agent.project_file:
        project_key = Path(agent.project_file).parent.name
        project = project_key
    elif agent.project_file:
        project_key = Path(agent.project_file).parent.name

    changespec = agent.cl_name
    if (
        agent.project_display_name
        and project_key
        and changespec.startswith(f"{project_key}_")
    ):
        changespec = (
            f"{agent.project_display_name}_{changespec[len(project_key) + 1 :]}"
        )
    context: list[str] = []
    if project and project != display_name:
        context.append(project)
    if changespec and changespec != display_name and changespec != project:
        context.append(changespec)
    return tuple(context)


def _agent_time_label(agent: Agent, *, now: datetime | None) -> str | None:
    timestamp, elapsed = compute_row_runtime(agent, now=now)
    parts: list[str] = []
    if timestamp is not None:
        completed = "".join(timestamp).strip()
        if completed:
            parts.append(completed)
    if elapsed:
        parts.append(elapsed)
    return " · ".join(parts) or None


def build_agent_panel_summary_snapshot(
    panel_key: PanelKey,
    agents: Sequence[Agent],
    *,
    unread_ids: Collection[AgentIdentity] = (),
    marked_ids: Collection[AgentIdentity] = (),
    now: datetime | None = None,
) -> AgentPanelSummarySnapshot:
    """Build a complete collapsed-panel snapshot from in-memory row data."""
    top_level_agents = [agent for agent in agents if not agent.is_child_row]
    projected = agent_summary_status_counts(top_level_agents, unread_ids)
    counts = _AgentPanelSummaryCounts(
        stopped=projected.stopped,
        running=projected.running,
        waiting=projected.waiting,
        failed=projected.failed,
        unread=projected.unread,
        done=projected.done,
    )

    by_suffix = {agent.raw_suffix: agent for agent in agents if agent.raw_suffix}
    rows: list[AgentPanelSummaryRow] = []
    for agent, block_root in _ordered_roster_agents(agents, unread_ids):
        display_name = _loaded_display_name(agent)
        rows.append(
            AgentPanelSummaryRow(
                identity=agent.identity,
                display_name=display_name,
                display_status=agent.display_status,
                status_bucket=status_bucket_for_values(
                    agent.status, agent.retried_as_timestamp
                ),
                roster_bucket=_row_roster_bucket(block_root, unread_ids),
                depth=_row_depth(agent, by_suffix),
                context=_agent_context(agent, display_name),
                model=agent.model,
                time_label=_agent_time_label(agent, now=now),
                is_marked=agent.identity in marked_ids,
                is_unread=agent.identity in unread_ids,
            )
        )

    root_count = sum(not agent.is_child_row for agent in agents)
    entry_count = len(agents)
    return AgentPanelSummarySnapshot(
        panel_key=panel_key,
        label=_collapsed_agent_panel_label(panel_key),
        entry_count=entry_count,
        root_count=root_count,
        nested_count=entry_count - root_count,
        counts=counts,
        rows=tuple(rows),
    )


__all__ = [
    "AgentPanelSummaryRow",
    "AgentPanelSummarySnapshot",
    "CollapsedAgentPanelFocus",
    "build_agent_panel_summary_snapshot",
]
