"""Synthetic fixtures for agent-artifact startup regression tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType


@dataclass(frozen=True)
class BundleArchiveFixture:
    """Paths and agents created for a dismissed-bundle archive fixture."""

    root: Path
    agents: list[Agent]
    corrupt_paths: list[Path]


@dataclass(frozen=True)
class RetryChainMarkerFixture:
    """Artifact marker dirs for a retry chain."""

    root: Path
    agents: tuple[Agent, Agent, Agent]
    marker_dirs: tuple[Path, Path, Path]


def make_agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    cl_name: str = "startup_cl",
    raw_suffix: str = "20250101120000",
    status: str = "DONE",
    workflow: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    step_index: int | None = None,
    step_name: str | None = None,
    step_output: dict[str, object] | None = None,
    retry_of_timestamp: str | None = None,
    retry_attempt: int = 0,
    retry_chain_root_timestamp: str | None = None,
    retried_as_timestamp: str | None = None,
) -> Agent:
    """Return a compact Agent row suitable for startup/archive tests."""

    start_time = datetime.strptime(raw_suffix[:14], "%Y%m%d%H%M%S")
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/projects/startup/startup.gp",
        status=status,
        start_time=start_time,
        raw_suffix=raw_suffix,
        workflow=workflow,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        step_index=step_index,
        step_name=step_name,
        step_output=step_output,
        retry_of_timestamp=retry_of_timestamp,
        retry_attempt=retry_attempt,
        retry_chain_root_timestamp=retry_chain_root_timestamp,
        retried_as_timestamp=retried_as_timestamp,
    )


def write_bundle(root: Path, agent: Agent, *, legacy_root: bool = False) -> Path:
    """Write *agent* to the same shard/name layout used by dismissed bundles."""

    if agent.raw_suffix is None:
        raise ValueError("fixture agents must have a raw suffix")
    name = f"{agent.raw_suffix}.json"
    if agent.is_workflow_child:
        step_index = agent.step_index if agent.step_index is not None else 0
        name = f"{agent.raw_suffix}__c{step_index}.json"
    directory = root if legacy_root else root / agent.raw_suffix[:6]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(agent.to_bundle_dict()), encoding="utf-8")
    return path


def build_dismissed_bundle_archive(
    root: Path,
    *,
    total: int = 10_000,
    legacy_count: int = 0,
    corrupt_count: int = 0,
) -> BundleArchiveFixture:
    """Create a large, sharded dismissed-bundle archive fixture.

    ``total`` controls valid bundle count. ``legacy_count`` places the first
    valid bundles in the archive root to exercise pre-shard compatibility.
    """

    agents: list[Agent] = []
    base = datetime(2025, 1, 1, 12, 0, 0)
    for idx in range(total):
        ts = (base + timedelta(hours=idx * 3)).strftime("%Y%m%d%H%M%S")
        agent = make_agent(cl_name=f"archive_{idx % 17}", raw_suffix=ts)
        agents.append(agent)
        write_bundle(root, agent, legacy_root=idx < legacy_count)

    corrupt_paths: list[Path] = []
    for idx in range(corrupt_count):
        ts = (base + timedelta(days=40, seconds=idx)).strftime("%Y%m%d%H%M%S")
        directory = root if idx < legacy_count else root / ts[:6]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{ts}.json"
        path.write_text("{not valid json", encoding="utf-8")
        corrupt_paths.append(path)

    return BundleArchiveFixture(root=root, agents=agents, corrupt_paths=corrupt_paths)


def build_workflow_collision_archive(root: Path) -> tuple[Agent, list[Agent], Agent]:
    """Create a parent plus ``__c`` children and one unrelated parent bundle."""

    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow_parent",
        raw_suffix="20250101120000",
        workflow="startup_workflow",
    )
    children = [
        make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=f"workflow_step_{idx}",
            raw_suffix=parent.raw_suffix or "20250101120000",
            parent_workflow=parent.workflow,
            parent_timestamp=parent.raw_suffix,
            step_index=idx,
            step_name=f"step_{idx}",
        )
        for idx in range(2)
    ]
    unrelated = make_agent(cl_name="unrelated", raw_suffix="20250101130000")

    write_bundle(root, parent)
    for child in children:
        write_bundle(root, child)
    write_bundle(root, unrelated)
    return parent, children, unrelated


def build_retry_chain_agents() -> tuple[Agent, Agent, Agent]:
    """Return a three-agent retry chain with forward and backward edges."""

    root = make_agent(
        cl_name="retry_chain",
        raw_suffix="20250101120000",
        status="FAILED",
        retry_attempt=0,
        retry_chain_root_timestamp="20250101120000",
        retried_as_timestamp="20250101121000",
    )
    child = make_agent(
        cl_name="retry_chain",
        raw_suffix="20250101121000",
        status="FAILED",
        retry_of_timestamp=root.raw_suffix,
        retry_attempt=1,
        retry_chain_root_timestamp=root.raw_suffix,
        retried_as_timestamp="20250101122000",
    )
    grandchild = make_agent(
        cl_name="retry_chain",
        raw_suffix="20250101122000",
        status="DONE",
        retry_of_timestamp=child.raw_suffix,
        retry_attempt=2,
        retry_chain_root_timestamp=root.raw_suffix,
    )
    return root, child, grandchild


def build_retry_chain_marker_edges(root: Path) -> RetryChainMarkerFixture:
    """Create artifact marker files with retry-chain forward/backward edges."""

    agents = build_retry_chain_agents()
    marker_dirs: list[Path] = []
    for agent in agents:
        if agent.raw_suffix is None:
            raise ValueError("retry fixture agents must have raw suffixes")
        marker_dir = root / agent.raw_suffix
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker_dirs.append(marker_dir)
        marker_payload = {
            "name": agent.agent_name or agent.cl_name,
            "model": agent.model,
            "llm_provider": agent.llm_provider,
            "retry_of_timestamp": agent.retry_of_timestamp,
            "retry_attempt": agent.retry_attempt,
            "retry_chain_root_timestamp": agent.retry_chain_root_timestamp,
            "retried_as_timestamp": agent.retried_as_timestamp,
        }
        done_payload = {
            "outcome": "completed" if agent.status == "DONE" else "failed",
            "retry_of_timestamp": agent.retry_of_timestamp,
            "retry_attempt": agent.retry_attempt,
            "retry_chain_root_timestamp": agent.retry_chain_root_timestamp,
            "retried_as_timestamp": agent.retried_as_timestamp,
        }
        (marker_dir / "agent_meta.json").write_text(
            json.dumps(marker_payload),
            encoding="utf-8",
        )
        (marker_dir / "done.json").write_text(
            json.dumps(done_payload),
            encoding="utf-8",
        )
    return RetryChainMarkerFixture(
        root=root,
        agents=agents,
        marker_dirs=(marker_dirs[0], marker_dirs[1], marker_dirs[2]),
    )
