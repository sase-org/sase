"""Golden tests for the agent-artifact SQLite index record summaries."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)

from .agent_scan_golden.fixture_builder import TS_ACE_RUN_RUNNING, TS_WORKFLOW_ROOT
from .core_agent_scan_helpers import core_agent_scan_fixture_root as _fixture_root


def test_index_query_honors_project_filters(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)

    indexed = query_agent_artifact_index(
        index_path,
        fixture_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=True,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=True,
        ),
        options=AgentArtifactScanOptionsWire(only_projects=("home",)),
    )

    assert {record.project_name for record in indexed.records} == {"home"}


def test_artifact_index_summarizes_starting_records(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)

    artifact_dir = str(
        fixture_root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RUNNING
    )
    with sqlite3.connect(index_path) as conn:
        row = conn.execute(
            "SELECT status, started_at FROM agent_artifacts WHERE artifact_dir = ?",
            (artifact_dir,),
        ).fetchone()

    assert row == ("starting", None)


def test_artifact_index_summarizes_wait_completed_records_as_running(
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
    data["wait_completed_at"] = "2026-05-13T16:00:00Z"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)

    artifact_dir = str(
        fixture_root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RUNNING
    )
    with sqlite3.connect(index_path) as conn:
        row = conn.execute(
            "SELECT status, started_at FROM agent_artifacts WHERE artifact_dir = ?",
            (artifact_dir,),
        ).fetchone()

    assert row == ("running", None)


def test_artifact_index_treats_workflow_state_hidden_as_hidden(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    state_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "workflow-three_phase"
        / TS_WORKFLOW_ROOT
        / "workflow_state.json"
    )
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["hidden"] = True
    state_path.write_text(json.dumps(data), encoding="utf-8")

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)

    artifact_dir = str(
        fixture_root
        / "myproj"
        / "artifacts"
        / "workflow-three_phase"
        / TS_WORKFLOW_ROOT
    )
    with sqlite3.connect(index_path) as conn:
        row = conn.execute(
            "SELECT hidden FROM agent_artifacts WHERE artifact_dir = ?",
            (artifact_dir,),
        ).fetchone()

    assert row == (1,)


def test_bounded_source_clan_context_reconciles_through_index(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    workflow = projects_root / "proj" / "artifacts" / "ace-run"
    declarer = workflow / "20260701000000"
    declarer.mkdir(parents=True)
    (declarer / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "toobig-0.declarer",
                "agent_clan": "toobig-0",
                "agent_clan_generation": "g1",
                "clan_tribe": "chop",
                "clan_summary": "Chop generation",
            }
        ),
        encoding="utf-8",
    )
    (declarer / "done.json").write_text(
        json.dumps({"outcome": "completed", "name": "toobig-0.declarer"}),
        encoding="utf-8",
    )
    joiner = workflow / "20260701000001"
    joiner.mkdir()
    (joiner / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "toobig-0.joiner",
                "agent_clan": "toobig-0",
                "agent_clan_generation": "g1",
            }
        ),
        encoding="utf-8",
    )
    (joiner / "waiting.json").write_text("{}", encoding="utf-8")

    bounded_source = scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(max_records=0, newest_first=True),
    )
    assert [record.timestamp for record in bounded_source.records] == ["20260701000001"]
    assert bounded_source.clan_context[0].clan_tribe is None
    assert bounded_source.clan_context[0].clan_summary is None

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root)
    reconciled = query_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            include_full_history=False,
        ),
    )

    assert [record.timestamp for record in reconciled.records] == ["20260701000001"]
    assert reconciled.clan_context[0].clan_tribe == "chop"
    assert reconciled.clan_context[0].clan_summary == "Chop generation"
