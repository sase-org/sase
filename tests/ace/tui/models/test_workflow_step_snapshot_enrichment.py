"""Snapshot-level coverage for workflow-step enrichment reuse.

A prompt step's own ``artifacts_dir`` marker field is, in every observed
writer and production sample, the same directory as its parent record's own
``artifact_dir`` -- so the snapshot has already parsed the exact
``agent_meta.json`` the step would otherwise re-read from disk. These tests
pin that reuse (and the filesystem fallback for a divergent ``artifacts_dir``)
so a future change can't silently reintroduce the per-step filesystem read.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agent_steps_from_snapshot,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    PromptStepMarkerWire,
)


def _snapshot(records: list[AgentArtifactRecordWire]) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )


def test_step_enrichment_reuses_parent_record_meta_without_filesystem_read(
    tmp_path: Path,
) -> None:
    # No agent_meta.json is ever written to disk under this directory: if
    # the loader fell back to a filesystem read for this step, model and
    # llm_provider would come back unset instead of the record's values.
    artifact_dir = tmp_path / "20260519090000"
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp="20260519090000",
        agent_meta=AgentMetaWire(model="gpt-test", llm_provider="codex"),
        prompt_steps=[
            PromptStepMarkerWire(
                file_name="prompt_step_001_bash.json",
                workflow_name="wf",
                step_name="bash",
                step_type="bash",
                step_index=0,
                total_steps=1,
                status="completed",
                artifacts_dir=str(artifact_dir),
            )
        ],
    )

    agents, _meta = load_workflow_agent_steps_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].model == "gpt-test"
    assert agents[0].llm_provider == "codex"


def test_step_enrichment_falls_back_to_filesystem_for_divergent_artifacts_dir(
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "20260519090000"
    record_dir.mkdir()
    step_dir = tmp_path / "other-dir"
    step_dir.mkdir()
    (step_dir / "agent_meta.json").write_text(
        json.dumps({"model": "from-disk"}), encoding="utf-8"
    )
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(record_dir),
        timestamp="20260519090000",
        agent_meta=AgentMetaWire(model="from-record"),
        prompt_steps=[
            PromptStepMarkerWire(
                file_name="prompt_step_001_bash.json",
                workflow_name="wf",
                step_name="bash",
                step_type="bash",
                step_index=0,
                total_steps=1,
                status="completed",
                artifacts_dir=str(step_dir),
            )
        ],
    )

    agents, _meta = load_workflow_agent_steps_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].model == "from-disk"
