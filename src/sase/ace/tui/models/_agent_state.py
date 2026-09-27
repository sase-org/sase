"""Dataclass state fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass

from ._agent_state_core import AgentStateCoreFields
from ._agent_state_fleet import AgentStateFleetFields
from ._agent_state_ops import AgentStateOperationsFields
from ._agent_state_plan import AgentStatePlanFields
from ._agent_state_queue import AgentStateQueueFields
from ._agent_state_session import AgentStateSessionFields

__all__ = ["AgentState"]


@dataclass
class AgentState(
    # NB: dataclass collects base fields in reverse MRO, so bases are listed
    # last-first to preserve the original __init__/field order.
    AgentStateFleetFields,
    AgentStateSessionFields,
    AgentStateQueueFields,
    AgentStateOperationsFields,
    AgentStatePlanFields,
    AgentStateCoreFields,
):
    """Mutable state stored for a single agent row."""


def _get_commit_entry_id(agent: AgentState) -> str | None:  # legacy compatibility alias
    return agent.stitch_id


def _set_commit_entry_id(
    agent: AgentState,
    value: str | None,
) -> None:  # legacy compatibility alias
    agent.stitch_id = value


AgentState.commit_entry_id = property(  # type: ignore[attr-defined] # legacy compatibility alias
    _get_commit_entry_id,
    _set_commit_entry_id,
)
