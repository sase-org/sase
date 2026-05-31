"""Connected-component planning for episode v2 collection."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir
from sase.memory.episodes._collector_engine import EpisodeCollectorEngine
from sase.memory.episodes._component_planner import ComponentPlanner
from sase.memory.episodes._component_roots import plan_metadata
from sase.memory.episodes._component_types import (
    EpisodeComponentEdge,
    EpisodeComponentPlan,
)
from sase.memory.episodes._models import EpisodeDraft, EpisodeSelector
from sase.memory.episodes.source_refs import normalize_source_path


def build_episode_component_plans(
    selector: EpisodeSelector | None = None,
    *,
    projects_root: Path | str | None = None,
    scan: AgentArtifactScanWire | None = None,
    repo_root: Path | str | None = None,
    chat_paths: Iterable[str | Path] | None = None,
    include_chat_catalog: bool = True,
) -> list[EpisodeComponentPlan]:
    """Build deterministic connected-component plans from strong lineage edges."""

    selected = selector or EpisodeSelector()
    if selected.explicit_selector_count() > 1:
        raise ValueError("specify only one of agent, artifact_dir, changespec, or chat")
    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else sase_projects_dir()
    )
    snapshot = scan if scan is not None else _scan_projects(root)
    planner = ComponentPlanner(
        selected,
        projects_root=root,
        scan=snapshot,
        repo_root=Path(repo_root).expanduser() if repo_root is not None else Path.cwd(),
        chat_paths=chat_paths,
        include_chat_catalog=include_chat_catalog,
    )
    return planner.build()


def collect_episode_draft_for_component_plan(
    plan: EpisodeComponentPlan,
    *,
    projects_root: Path | str | None = None,
    scan: AgentArtifactScanWire | None = None,
    repo_root: Path | str | None = None,
) -> EpisodeDraft:
    """Collect one rich source graph constrained to a component plan."""

    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else sase_projects_dir()
    )
    snapshot = scan if scan is not None else _scan_projects(root)
    component_artifact_keys = {
        normalize_source_path(path) for path in plan.artifact_dirs
    }
    component_chat_paths = {normalize_source_path(path) for path in plan.chat_paths}
    collector = EpisodeCollectorEngine(
        EpisodeSelector(project=plan.project),
        projects_root=root,
        scan=snapshot,
        repo_root=Path(repo_root).expanduser() if repo_root is not None else Path.cwd(),
        component_artifact_keys=component_artifact_keys,
        component_chat_paths=component_chat_paths,
        component_metadata=plan_metadata(plan),
    )
    return collector.collect_component(
        artifact_dirs=plan.artifact_dirs,
        chat_paths=plan.chat_paths,
    )


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
    "EpisodeComponentEdge",
    "EpisodeComponentPlan",
    "build_episode_component_plans",
    "collect_episode_draft_for_component_plan",
]
