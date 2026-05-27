"""Deterministic source-graph collector for episodic-memory drafts."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.memory.episodes._collector_engine import EpisodeCollectorEngine
from sase.memory.episodes._models import EpisodeDraft, EpisodeSelector


def collect_episode_draft(
    selector: EpisodeSelector | None = None,
    *,
    projects_root: Path | str | None = None,
    scan: AgentArtifactScanWire | None = None,
    repo_root: Path | str | None = None,
) -> EpisodeDraft:
    """Collect one deterministic source graph from agent/chat/ChangeSpec inputs."""

    selected = selector or EpisodeSelector()
    if selected.explicit_selector_count() > 1:
        raise ValueError("specify only one of agent, artifact_dir, changespec, or chat")
    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else Path.home() / ".sase" / "projects"
    )
    snapshot = scan if scan is not None else _scan_projects(root)
    collector = EpisodeCollectorEngine(
        selected,
        projects_root=root,
        scan=snapshot,
        repo_root=Path(repo_root).expanduser() if repo_root is not None else Path.cwd(),
    )
    return collector.collect()


def _scan_projects(projects_root: Path) -> AgentArtifactScanWire:
    return scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=True,
            include_raw_prompt_snippets=False,
            include_done_markers=True,
            include_workflow_state=True,
            include_waiting=True,
        ),
    )


__all__ = [
    "EpisodeDraft",
    "EpisodeSelector",
    "collect_episode_draft",
]
