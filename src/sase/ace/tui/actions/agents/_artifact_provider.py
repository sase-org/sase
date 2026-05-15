"""ACE agent artifact provider helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.agent_artifact_facade import AgentArtifact, list_agent_artifacts

from ...models.agent import Agent


@dataclass(frozen=True)
class _AgentArtifactPage:
    artifacts: list[AgentArtifact] = field(default_factory=list)
    request: object | None = None
    shared_snapshot: object | None = None


@dataclass(frozen=True)
class _ArtifactReadResult:
    value: _AgentArtifactPage
    used_daemon: bool = False


def read_agent_artifacts_for_tui(
    agent: Agent,
    *,
    selection_generation: object | None = None,
    args: Any | None = None,
    client: Any | None = None,
) -> _ArtifactReadResult:
    """Return selected-agent artifacts from direct source stores."""
    _ = (selection_generation, args, client)
    artifacts_dir = agent.get_artifacts_dir()
    artifacts = [] if artifacts_dir is None else list_agent_artifacts(artifacts_dir)
    return _ArtifactReadResult(value=_AgentArtifactPage(artifacts=artifacts))
