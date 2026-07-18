"""Messages emitted by asynchronous prompt-panel enrichment."""

from textual.message import Message


class AgentDetailHeaderEnriched(Message):
    """Cached detail-header metadata refreshed for an agent."""

    def __init__(self, agent_identity: tuple[object, ...]) -> None:
        super().__init__()
        self.agent_identity = agent_identity


class ClanSectionSnapshotLoaded(Message):
    """Disk-backed clan section data refreshed for a selected clan."""

    def __init__(self, agent_identity: tuple[object, ...]) -> None:
        super().__init__()
        self.agent_identity = agent_identity
