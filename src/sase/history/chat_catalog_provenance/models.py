"""Public models for the headless chat provenance catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChatProvenance = Literal["local", "shared", "remote", "unknown"]
CHAT_PROVENANCE_VALUES: tuple[ChatProvenance, ...] = (
    "local",
    "shared",
    "remote",
    "unknown",
)


@dataclass(frozen=True, slots=True)
class ChatCatalogEntry:
    """One transcript enriched with agent and synchronization provenance."""

    path: str
    absolute_path: str
    basename: str
    mtime: str
    size_bytes: int
    workflow: str | None
    agent: str | None
    timestamp: str | None
    prompt_snippet: str | None
    response_snippet: str | None
    provenance: ChatProvenance
    source_machine: str | None
    source_username: str | None
    project_key: str | None
    agent_artifact_dir: str | None
    agent_local_name: str | None
    agent_global_name: str | None
    sidecar_repo: str | None
    sidecar_relpath: str | None
    publication_pending: bool
    publication_last_error: str | None
    publication_attempts: int | None = None


@dataclass(frozen=True, slots=True)
class ChatCatalogSnapshot:
    """An immutable catalog result and its pre-limit summary metadata."""

    entries: tuple[ChatCatalogEntry, ...]
    provenance_counts: dict[ChatProvenance, int]
    remote_machines: frozenset[str]
    truncated: bool
    diagnostics: tuple[str, ...] = ()

    @property
    def counts(self) -> dict[ChatProvenance, int]:
        """Compatibility shorthand for consumers rendering summary chips."""

        return self.provenance_counts


@dataclass(frozen=True, slots=True)
class AgentChatLink:
    """Internal transcript-to-agent link retained in the persistent cache."""

    project_key: str
    artifact_dir: str
    artifact_dirs: tuple[str, ...]
    local_name: str | None
    global_name: str | None
    source_machine: str | None
    source_username: str | None
    imported: bool


@dataclass(frozen=True, slots=True)
class SidecarAgent:
    """Published agent metadata read from one agents sidecar checkout."""

    global_name: str
    machine: str | None
    username: str | None
    relpath: str


@dataclass(frozen=True, slots=True)
class SidecarProjectIndex:
    """Readability and published names for one project sidecar."""

    project_key: str
    sidecar_path: str
    readable: bool
    agents: dict[str, SidecarAgent]
    diagnostic: str | None = None


__all__ = [
    "CHAT_PROVENANCE_VALUES",
    "AgentChatLink",
    "ChatCatalogEntry",
    "ChatCatalogSnapshot",
    "ChatProvenance",
    "SidecarAgent",
    "SidecarProjectIndex",
]
