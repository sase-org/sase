"""Shared data types for episode component planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any

from sase.core.episode_wire import EpisodeWeakRefsWire


@dataclass(frozen=True)
class EpisodeComponentEdge:
    """A deterministic strong edge used to define component membership."""

    kind: str
    from_key: str
    to_key: str
    evidence_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeComponentPlan:
    """One connected episode component selected for collection."""

    project: str
    component_key: str
    component_root_kind: str
    root_timestamp: str | None
    root_chat_key: str | None
    artifact_dirs: list[str]
    chat_paths: list[str]
    strong_edges: list[EpisodeComponentEdge]
    weak_refs: EpisodeWeakRefsWire
    seed_reason: str
    existing_episode_ids: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return (
            json.dumps(
                self.to_json_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


__all__ = [
    "EpisodeComponentEdge",
    "EpisodeComponentPlan",
]
