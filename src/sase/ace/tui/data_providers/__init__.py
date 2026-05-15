"""ACE data-provider abstractions for read-heavy TUI surfaces."""

from __future__ import annotations

from ..provider_contract import (
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceRowHandle,
    AceSnapshot,
)
from ._direct import DirectAgentsDataProvider
from ._factory import make_agents_data_provider
from ._handles import agent_row_handle
from ._settings import agents_daemon_reads_enabled
from ._snapshots import agent_snapshot
from ._types import (
    AgentEventApplyResult,
    AgentsProviderSnapshot,
    AgentsDataProvider,
    AgentsViewport,
)

_AgentEventApplyResult = AgentEventApplyResult
_AgentsProviderSnapshot = AgentsProviderSnapshot
_DirectAgentsDataProvider = DirectAgentsDataProvider
_agent_snapshot = agent_snapshot

__all__ = [
    "AceFallbackMetadata",
    "AceProviderCapabilities",
    "AceProviderInfo",
    "AceRowHandle",
    "AceSnapshot",
    "AgentEventApplyResult",
    "AgentsDataProvider",
    "AgentsProviderSnapshot",
    "AgentsViewport",
    "DirectAgentsDataProvider",
    "_AgentEventApplyResult",
    "_AgentsProviderSnapshot",
    "_DirectAgentsDataProvider",
    "_agent_snapshot",
    "agent_row_handle",
    "agents_daemon_reads_enabled",
    "make_agents_data_provider",
]
