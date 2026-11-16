"""Tests for targeted agent-artifact lookup wires and the thin facade."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_lookup import lookup_agent_artifacts
from sase.core.agent_artifact_lookup_wire import (
    AGENT_ARTIFACT_LOOKUP_FALLBACK_BUDGET,
    AgentArtifactLookupQueryWire,
    AgentArtifactLookupTargetWire,
    agent_artifact_lookup_query_to_dict,
    agent_artifact_lookup_result_from_dict,
)
from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION


def test_lookup_schema_and_budget_are_pinned() -> None:
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 38
    assert AGENT_ARTIFACT_LOOKUP_FALLBACK_BUDGET == 200


def test_lookup_query_round_trips_targets() -> None:
    query = AgentArtifactLookupQueryWire(
        target=AgentArtifactLookupTargetWire(kind="session", names=("lane-a",)),
        include_hidden=False,
        forced_unavailability="busy",
    )
    payload = agent_artifact_lookup_query_to_dict(query)
    assert payload == {
        "target": {"kind": "session", "names": ["lane-a"]},
        "include_hidden": False,
        "forced_unavailability": "busy",
    }
    restored = agent_artifact_lookup_result_from_dict(
        {
            "schema_version": 38,
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "query": payload,
            "availability": "busy",
            "complete": False,
            "source": "fallback",
            "hits": [
                {
                    "artifact_dir": "/tmp/a",
                    "project_name": "proj",
                    "workflow_dir_name": "ace-run",
                    "timestamp": "20261116120000",
                    "has_done_marker": False,
                    "has_running_marker": False,
                    "hidden": False,
                    "agent_name": "lane-a--plan",
                    "lookup_session": "lane-a",
                    "match_kind": "session",
                }
            ],
            "truncated": False,
            "dirs_visited": 1,
            "records_decoded": 1,
        }
    )
    assert restored.availability == "busy"
    assert restored.query.target.kind == "session"
    assert restored.hits[0].lookup_session == "lane-a"
    assert restored.hits[0].match_kind == "session"


def test_lookup_facade_selects_indexed_name(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    artifact = projects / "proj" / "artifacts" / "ace-run" / "20261116120000"
    artifact.mkdir(parents=True)
    (artifact / "agent_meta.json").write_text(
        '{"name":"lane-a--plan","workflow_name":"lane-a","agent_session":"lane-a"}',
        encoding="utf-8",
    )
    index = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index, projects)
    result = lookup_agent_artifacts(
        index,
        projects,
        AgentArtifactLookupQueryWire(
            target=AgentArtifactLookupTargetWire(
                kind="names",
                names=("lane-a--plan",),
            )
        ),
    )
    assert result.availability == "ready"
    assert result.complete
    assert result.source == "index"
    assert result.hits[0].agent_name == "lane-a--plan"
    assert result.hits[0].lookup_session == "lane-a"
    assert result.hits[0].match_kind == "exact"
