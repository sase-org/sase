"""Reasoning-effort metadata read-back and scanner projection tests."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import AgentMetaWire
from tests._enrich_agent_helpers import make_agent


def test_enrich_filesystem_reads_effort(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "llm_provider": "claude",
                "reasoning_effort": "xhigh",
                "model_alias": "medium",
            }
        ),
        encoding="utf-8",
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.reasoning_effort == "xhigh"
    assert agent.model_alias == "medium"


def test_enrich_wire_reads_effort() -> None:
    agent = make_agent(status="RUNNING")
    meta = AgentMetaWire(
        model="opus",
        llm_provider="claude",
        reasoning_effort="xhigh",
        model_alias="medium",
    )

    enrich_agent_from_meta_wire(agent, meta, None)

    assert agent.reasoning_effort == "xhigh"
    assert agent.model_alias == "medium"


def test_enrich_filesystem_without_effort_leaves_none(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"model": "opus", "llm_provider": "claude"}),
        encoding="utf-8",
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.reasoning_effort is None


def test_rust_scan_projects_reasoning_effort(tmp_path: Path) -> None:
    """The real Rust scanner projects ``reasoning_effort`` from both markers."""
    from sase.core.agent_scan_facade import scan_agent_artifacts

    artifact_dir = (
        tmp_path / "projects" / "myproj" / "artifacts" / "ace-run" / "20260623120000"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "llm_provider": "claude",
                "reasoning_effort": "xhigh",
                "model_alias": "medium",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "completed",
                "cl_name": "c",
                "project_file": "/tmp/myproj.sase",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "prompt_step_s1.json").write_text(
        json.dumps(
            {
                "workflow_name": "wf",
                "step_name": "s1",
                "step_type": "agent",
                "status": "completed",
                "model": "opus",
                "llm_provider": "claude",
                "reasoning_effort": "high",
                "model_alias": "workflow_plan",
            }
        ),
        encoding="utf-8",
    )

    snapshot = scan_agent_artifacts(tmp_path / "projects")

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.reasoning_effort == "xhigh"
    assert record.agent_meta.model_alias == "medium"
    assert record.prompt_steps[0].reasoning_effort == "high"
    assert record.prompt_steps[0].model_alias == "workflow_plan"
