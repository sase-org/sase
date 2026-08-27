from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models._projected_record import (
    hydrate_projected_agent,
    resolve_linked_repos,
)
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PromptStepMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
)


def _record(artifact_dir: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/projects/proj",
        project_file="/tmp/projects/proj/proj.sase",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp="20260519090000",
        agent_meta=AgentMetaWire(
            linked_repos=[
                {
                    "name": "sase-core",
                    "workspace_dir": "/tmp/sase-core",
                }
            ]
        ),
        done=DoneMarkerWire(
            step_output={
                "_raw": "full text",
                "meta_keep": "loaded",
            }
        ),
        workflow_state=WorkflowStateWire(
            workflow_name="wf",
            steps=[
                WorkflowStepStateWire(
                    name="build",
                    output={"_raw": "workflow output", "meta_parent": "loaded"},
                )
            ],
        ),
        prompt_steps=[
            PromptStepMarkerWire(
                file_name="prompt_step_001_first.json",
                workflow_name="wf",
                step_name="first",
                step_index=0,
                output={"_raw": "wrong step"},
            ),
            PromptStepMarkerWire(
                file_name="prompt_step_002_target.json",
                workflow_name="wf",
                step_name="target",
                step_index=1,
                output={"_raw": "target output", "meta_keep": "loaded"},
            ),
        ],
    )


def test_hydrate_projected_done_agent_loads_output_and_linked_repos(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    artifact_dir = "/tmp/projects/proj/artifacts/ace-run/20260519090000"

    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.load_agent_artifact_records",
        lambda _index, _dirs: [_record(artifact_dir)],
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 19, 9, 0, 0),
        raw_suffix="20260519090000",
        step_output={"meta_keep": "projected"},
        record_shape="list",
        index_record_dir=artifact_dir,
    )

    assert hydrate_projected_agent(agent) is True

    assert agent.record_shape == "full"
    assert agent.step_output == {
        "_raw": "full text",
        "meta_keep": "loaded",
    }
    assert agent.linked_repos == (LinkedRepoMetadata("sase-core", "/tmp/sase-core"),)


def test_hydrate_projected_workflow_step_uses_prompt_step_file_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    artifact_dir = "/tmp/projects/proj/artifacts/ace-run/20260519090000"

    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.load_agent_artifact_records",
        lambda _index, _dirs: [_record(artifact_dir)],
    )
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="target",
        project_file="/tmp/projects/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 19, 9, 0, 0),
        raw_suffix="20260519090000",
        parent_workflow="wf",
        parent_timestamp="20260519090000",
        step_name="target",
        step_index=1,
        prompt_step_file_name="prompt_step_002_target.json",
        record_shape="list",
        index_record_dir=artifact_dir,
    )

    assert resolve_linked_repos(agent, hydrate=True) == (
        LinkedRepoMetadata("sase-core", "/tmp/sase-core"),
    )

    assert agent.record_shape == "full"
    assert agent.step_output == {
        "_raw": "target output",
        "meta_keep": "loaded",
    }
