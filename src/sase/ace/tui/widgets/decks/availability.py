"""No-I/O availability probes for deck subtitles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from collections.abc import Mapping

from ..file_panel._file_list import desired_file_pages
from .._llm_calls_panel_fetching import cached_tool_call_count
from .._agent_detail_helpers import _ACTIVE_STATUSES

if TYPE_CHECKING:
    from ...models.agent import Agent
    from .model import DeckId


@dataclass(frozen=True)
class DeckAvailability:
    """Content presence for one deck; None means unknown."""

    has_content: bool | None
    count: int | None


DeckAvailabilitySet = Mapping["DeckId", DeckAvailability]


def probe_files_deck(agent: Agent, *, attempt_number: int | None) -> DeckAvailability:
    """Probe Files availability without I/O."""
    if attempt_number is not None:
        return DeckAvailability(False, 0)
    if agent.is_clan_container or agent.is_proc_shell:
        return DeckAvailability(False, 0)
    if agent.is_workflow_child and agent.step_type in ("bash", "python"):
        return DeckAvailability(False, 0)
    pages, _default = desired_file_pages(agent)
    if pages:
        return DeckAvailability(True, len(pages))
    if agent.status not in _ACTIVE_STATUSES and getattr(agent, "all_files", None):
        all_files = list(agent.all_files)
        if all_files:
            return DeckAvailability(True, len(all_files))
    if agent.status in _ACTIVE_STATUSES:
        return DeckAvailability(None, None)
    if agent.workspace_num is not None and not agent.fleet_origin_alias:
        return DeckAvailability(None, None)
    return DeckAvailability(False, 0)


def probe_tools_deck(agent: Agent, *, attempt_number: int | None) -> DeckAvailability:
    """Probe Tools availability without I/O."""
    from ...llm_calls import supports_slow_tool_sources

    if attempt_number is not None:
        return DeckAvailability(False, 0)
    if agent.is_clan_container or agent.is_proc_shell:
        return DeckAvailability(False, 0)
    if not supports_slow_tool_sources(agent):
        return DeckAvailability(False, 0)
    count = cached_tool_call_count(agent)
    if count is None:
        return DeckAvailability(None, None)
    if count == 0:
        return DeckAvailability(False, 0)
    return DeckAvailability(True, count)
