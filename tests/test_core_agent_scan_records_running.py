"""Golden tests for running agent scan record metadata."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire

from .agent_scan_golden.fixture_builder import TS_ACE_RUN_RUNNING
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    record_by_timestamp,
)


def test_running_record_carries_agent_meta(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)
    assert rec.workflow_dir_name == "ace-run"
    assert rec.project_name == "myproj"
    assert rec.has_done_marker is False
    assert rec.done is None
    assert rec.agent_meta is not None
    assert rec.agent_meta.name == "running_alpha"
    assert rec.agent_meta.workflow_name == "wf_alpha"
    assert rec.agent_meta.pid == 22222
    assert rec.agent_meta.plan is True
    assert rec.agent_meta.plan_approved is False
    assert rec.agent_meta.plan_committed is False
    assert rec.agent_meta.wait_for == ["bob", "carol"]
    assert rec.agent_meta.wait_duration == 3600.0
    assert rec.agent_meta.workspace_dir == "/tmp/workspaces/alpha"


def test_running_record_carries_commit_diff_path_through_scan_and_index(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["commit_diff_path"] = "/tmp/running_commit.diff"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)
    assert rec.agent_meta is not None
    assert rec.agent_meta.commit_diff_path == "/tmp/running_commit.diff"

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)
    indexed = query_agent_artifact_index(
        index_path,
        fixture_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            include_full_history=False,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=True,
        ),
    )
    indexed_rec = record_by_timestamp(indexed, TS_ACE_RUN_RUNNING)
    assert indexed_rec.agent_meta is not None
    assert indexed_rec.agent_meta.commit_diff_path == "/tmp/running_commit.diff"


def test_running_record_carries_output_variables_through_scan_and_index(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["output_variables"] = {
        "report_path": "/tmp/report.md",
        "status": "ok",
        "attempts": 2,
    }
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)
    assert rec.agent_meta is not None
    assert rec.agent_meta.output_variables == {
        "report_path": "/tmp/report.md",
        "status": "ok",
    }

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)
    indexed = query_agent_artifact_index(
        index_path,
        fixture_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            include_full_history=False,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=True,
        ),
    )
    indexed_rec = record_by_timestamp(indexed, TS_ACE_RUN_RUNNING)
    assert indexed_rec.agent_meta is not None
    assert indexed_rec.agent_meta.output_variables == {
        "report_path": "/tmp/report.md",
        "status": "ok",
    }


def test_running_record_linked_repos_survive_scan_index_and_enrichment(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["linked_repos"] = [
        {
            "name": "sase-core",
            "workspace_dir": "/tmp/workspaces/sase-core_14",
            "workspace_strategy": "suffix",
        },
        "ignored",
        {
            "name": "sase-github",
            "workspace_dir": "/tmp/workspaces/sase-github_14",
            "workspace_strategy": "suffix",
        },
    ]
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)
    assert rec.agent_meta is not None
    assert rec.agent_meta.linked_repos == [
        {
            "name": "sase-core",
            "workspace_dir": "/tmp/workspaces/sase-core_14",
            "workspace_strategy": "suffix",
        },
        {
            "name": "sase-github",
            "workspace_dir": "/tmp/workspaces/sase-github_14",
            "workspace_strategy": "suffix",
        },
    ]

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)
    indexed = query_agent_artifact_index(
        index_path,
        fixture_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            include_full_history=False,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=True,
        ),
    )
    indexed_rec = record_by_timestamp(indexed, TS_ACE_RUN_RUNNING)
    assert indexed_rec.agent_meta is not None

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_alpha",
        project_file=str(fixture_root / "myproj" / "myproj.sase"),
        status="STARTING",
        start_time=None,
    )
    enrich_agent_from_meta_wire(
        agent,
        indexed_rec.agent_meta,
        indexed_rec.waiting,
        indexed_rec.pending_question,
    )

    assert agent.linked_repos == (
        LinkedRepoMetadata(
            name="sase-core",
            workspace_dir="/tmp/workspaces/sase-core_14",
        ),
        LinkedRepoMetadata(
            name="sase-github",
            workspace_dir="/tmp/workspaces/sase-github_14",
        ),
    )


def test_running_record_carries_wait_completed_at(fixture_root: Path) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["wait_completed_at"] = "2026-05-13T16:00:00Z"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.wait_completed_at == "2026-05-13T16:00:00Z"


def test_running_record_carries_auto_approve_plan_action(
    fixture_root: Path,
) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["auto_approve_plan_action"] = "epic"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.auto_approve_plan_action == "epic"


def test_running_record_carries_agent_meta_tag(fixture_root: Path) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["tag"] = "sase-26"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.tag == "sase-26"


def test_scalar_plan_submitted_at_is_preserved(fixture_root: Path) -> None:
    timestamp = "2026-04-27T11:05:00Z"
    epic_timestamp = "2026-04-27T11:08:00Z"
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["plan_submitted_at"] = timestamp
    data["epic_started_at"] = epic_timestamp
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.plan_submitted_at == [timestamp]
    assert rec.agent_meta.epic_started_at == epic_timestamp
