"""Rebuild TUI agent objects from repro bundle rows."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sase.ace.tui.models.agent import Agent, AgentType

from .schema import AgentIdentity, ReproAgentRow, ReproLoadState

if TYPE_CHECKING:
    from sase.ace.tui.models.agent_loader import AgentLoadState


def _agent_identity_to_repro(
    identity: tuple[AgentType, str, str | None],
) -> AgentIdentity:
    """Convert a runtime ``Agent.identity`` tuple to bundle identity form."""

    return (identity[0].value, identity[1], identity[2])


def agent_to_repro_identity(agent: Agent) -> AgentIdentity:
    return _agent_identity_to_repro(agent.identity)


def load_state_from_repro(state: ReproLoadState) -> AgentLoadState:
    """Convert a serialized repro load state to the runtime dataclass."""

    from sase.ace.tui.models.agent_loader import AgentLoadState

    return AgentLoadState(
        tier=state.tier,
        complete_history=state.complete_history,
        complete_visible_inbox=state.complete_visible_inbox,
        artifact_source=state.artifact_source,
        used_artifact_index=state.used_artifact_index,
        index_error=state.index_error,
        repair_recommended=state.repair_recommended,
        repair_reason=state.repair_reason,
        truncated=state.truncated,
    )


def _agent_from_repro_row(row: ReproAgentRow) -> Agent:
    """Build an ``Agent`` with the fields needed by the real Agents-tab path."""

    agent = Agent(
        agent_type=AgentType(row.agent_type),
        cl_name=row.cl_name,
        project_file=f"/tmp/sase-repro/{row.cl_name}.sase",
        status=row.status,
        start_time=_parse_start_time(row.raw_suffix),
        workspace_num=row.workspace_num,
        workflow=row.workflow,
        pid=row.pid,
        raw_suffix=row.raw_suffix,
        parent_workflow=row.parent_workflow,
        parent_timestamp=row.parent_timestamp,
        step_type=row.step_type,
        appears_as_agent=row.appears_as_agent,
        agent_name=row.agent_name,
        tribe=row.tribe,
    )

    metadata = row.metadata
    agent.llm_provider = _optional_str(metadata.get("llm_provider"))
    agent.vcs_provider = _optional_str(metadata.get("vcs_provider"))
    agent.role_suffix = _optional_str(metadata.get("role_suffix"))
    agent.retry_attempt = _optional_int(metadata.get("retry_attempt")) or 0
    agent.step_index = _optional_int(metadata.get("step_index"))
    return agent


def agents_from_repro_rows(rows: list[ReproAgentRow]) -> list[Agent]:
    return [_agent_from_repro_row(row) for row in rows]


def _parse_start_time(raw_suffix: str | None) -> datetime | None:
    if raw_suffix is None or len(raw_suffix) < 14:
        return None
    try:
        return datetime.strptime(raw_suffix[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object, *, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default
