"""Shared fixtures for projected-detail retention tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
)


def full_record(artifact_dir: str, timestamp: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="retention-proj",
        project_dir="/tmp/projects/retention-proj",
        project_file="/tmp/projects/retention-proj/retention-proj.sase",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=timestamp,
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
                "_raw": "full detail output " * 5000,
                "meta_keep": "loaded",
            }
        ),
    )


def list_agent(
    timestamp: str,
    artifact_dir: str,
    *,
    cl_name: str = "retention-proj",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/retention-proj/retention-proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 19, 9, 0, 0),
        raw_suffix=timestamp,
        step_output={"meta_keep": "projected"},
        record_shape="list",
        index_record_dir=artifact_dir,
    )


def stamp(timestamp_base: int, i: int) -> str:
    return f"{timestamp_base + i:014d}"
