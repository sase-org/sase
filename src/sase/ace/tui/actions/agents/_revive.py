"""Agent revival methods for the ace TUI app.

This module remains the public import facade for :class:`AgentRevivalMixin`.
The implementation lives in smaller focused mixins nearby.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._revive_archive import AgentReviveArchiveMixin
from ._revive_execution import AgentReviveExecutionMixin
from ._revive_flow import AgentReviveFlowMixin
from ._revive_group_resolution import (
    pop_agent_for_group_ref,
    pop_first_matching_agent,
    ref_label,
    resolve_saved_group_agents,
    utc_wire_timestamp,
)
from ._revive_helpers import (
    is_child_of,
    merge_dismissed_agents,
    revived_artifact_dir,
    schedule_revive_full_history_refresh,
)
from ._revive_index import (
    sync_dismissed_agent_artifact_index,
    upsert_agent_artifact_index_artifacts,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

_is_child_of = is_child_of
_merge_dismissed_agents = merge_dismissed_agents
_pop_agent_for_group_ref = pop_agent_for_group_ref
_pop_first_matching_agent = pop_first_matching_agent
_ref_label = ref_label
_resolve_saved_group_agents = resolve_saved_group_agents
_revived_artifact_dir = revived_artifact_dir
_schedule_revive_full_history_refresh = schedule_revive_full_history_refresh
_utc_wire_timestamp = utc_wire_timestamp


class AgentRevivalMixin(
    AgentReviveFlowMixin,
    AgentReviveArchiveMixin,
    AgentReviveExecutionMixin,
):
    """Mixin providing agent revival (un-dismiss) functionality.

    Overrides action_start_rewind to dispatch to revive flow when on the
    Agents tab, otherwise delegates to the original rewind behavior.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: str
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _current_group_key: tuple[str, ...] | None
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _revived_agent_raw_suffixes: set[str]


__all__ = [
    "AgentRevivalMixin",
    "sync_dismissed_agent_artifact_index",
    "upsert_agent_artifact_index_artifacts",
    "_is_child_of",
    "_merge_dismissed_agents",
    "_pop_agent_for_group_ref",
    "_pop_first_matching_agent",
    "_ref_label",
    "_resolve_saved_group_agents",
    "_revived_artifact_dir",
    "_schedule_revive_full_history_refresh",
    "_utc_wire_timestamp",
]
