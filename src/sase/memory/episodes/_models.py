"""Public data models for episodic-memory collection."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.core.episode_facade import generate_episode_id
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)


@dataclass(frozen=True)
class EpisodeSelector:
    """Selector for one deterministic source graph collection."""

    project: str | None = None
    agent: str | None = None
    artifact_dir: str | Path | None = None
    changespec: str | None = None
    chat: str | Path | None = None
    since: str | None = None
    until: str | None = None
    limit: int | None = None

    def explicit_selector_count(self) -> int:
        return sum(
            value is not None
            for value in (self.agent, self.artifact_dir, self.changespec, self.chat)
        )

    def selector_kind(self) -> str:
        if self.agent is not None:
            return "agent"
        if self.artifact_dir is not None:
            return "artifact_dir"
        if self.changespec is not None:
            return "changespec"
        if self.chat is not None:
            return "chat"
        return "project_scan"

    def selector_value(self) -> str | None:
        value: str | Path | None
        if self.agent is not None:
            value = self.agent
        elif self.artifact_dir is not None:
            value = self.artifact_dir
        elif self.changespec is not None:
            value = self.changespec
        elif self.chat is not None:
            value = self.chat
        else:
            value = self.project
        return str(value) if value is not None else None


@dataclass(frozen=True)
class EpisodeChatTurnRef:
    """A bounded chat turn reference attached to a source graph."""

    id: str
    chat_source_id: str
    chat_path: str
    turn_index: int
    prompt_excerpt: str | None = None
    response_excerpt: str | None = None


@dataclass(frozen=True)
class EpisodeDraft:
    """In-memory collector output; storage/rendering happen in later phases."""

    schema_version: int
    project: str
    selector_kind: str
    selector_value: str | None
    root_source_id: str
    root_node_id: str
    sources: list[EpisodeSourceRefWire]
    nodes: list[EpisodeNodeWire]
    edges: list[EpisodeEdgeWire]
    events: list[EpisodeEventWire]
    chat_turns: list[EpisodeChatTurnRef]
    metadata: dict[str, str]
    warnings: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection of this draft."""

        return asdict(self)

    def to_json(self) -> str:
        """Serialize this draft in stable key order for byte-stability tests."""

        return (
            json.dumps(
                self.to_json_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )

    def to_episode_wire(
        self,
        *,
        title: str = "Episode Draft",
        summary: str = "Collected deterministic source graph.",
    ) -> EpisodeWire:
        """Project the draft graph to an ``EpisodeWire`` without lessons."""

        episode_id = generate_episode_id(
            self.project,
            self.root_source_id,
            self.sources,
        )
        return EpisodeWire(
            schema_version=EPISODE_WIRE_SCHEMA_VERSION,
            episode_id=episode_id,
            project=self.project,
            title=title,
            summary=summary,
            root_source_id=self.root_source_id,
            sources=self.sources,
            nodes=self.nodes,
            edges=self.edges,
            events=self.events,
            lessons=[],
            metadata={
                **self.metadata,
                "selector_kind": self.selector_kind,
                "selector_value": self.selector_value or "",
            },
        )
