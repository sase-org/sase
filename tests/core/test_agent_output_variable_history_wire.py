"""Tests for the Python output-variable history wire and facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_output_variable_history_wire import (
    AGENT_OUTPUT_VARIABLE_HISTORY_WIRE_SCHEMA_VERSION,
    AgentOutputVariableHistoryQueryWire,
    agent_output_variable_history_from_dict,
    agent_output_variable_history_query_to_dict,
)
from sase.core.agent_scan_facade import query_agent_output_variable_history
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION


def test_history_schema_versions_are_pinned() -> None:
    assert AGENT_OUTPUT_VARIABLE_HISTORY_WIRE_SCHEMA_VERSION == 1
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 22


def test_history_query_round_trips_defaults_and_filters() -> None:
    query = AgentOutputVariableHistoryQueryWire(
        projects=["sase"],
        agents=["build.*"],
        keys=["status"],
        values=["ok"],
        since_timestamp="20260814000000",
        until_timestamp="20260814235959",
        include_hidden=True,
        key_limit=0,
        value_limit=3,
        reverse=True,
    )

    payload = agent_output_variable_history_query_to_dict(query)
    restored = agent_output_variable_history_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "query": payload,
            "keys_limit": {
                "limit": 0,
                "total_count": 2,
                "returned_count": 2,
                "truncated": False,
            },
            "groups": [
                {
                    "key": "status",
                    "occurrence_count": 2,
                    "distinct_value_count": 1,
                    "values_limit": {
                        "limit": 3,
                        "total_count": 1,
                        "returned_count": 1,
                        "truncated": False,
                    },
                    "values": [
                        {
                            "value": "ok",
                            "value_json": '"ok"',
                            "occurrence_count": 2,
                            "agent_count": 2,
                            "agents": ["build", "build.worker"],
                            "projects": ["sase"],
                            "first_seen_timestamp": "20260814010101",
                            "last_seen_timestamp": "20260814111111",
                            "newest": {
                                "artifact_dir": "/tmp/a",
                                "project_name": "sase",
                                "workflow_dir_name": "ace-run",
                                "timestamp": "20260814111111",
                                "agent_name": "build.worker",
                                "cl_name": "sase",
                                "key": "status",
                                "value": "ok",
                                "value_json": '"ok"',
                                "hidden": False,
                            },
                        }
                    ],
                }
            ],
        }
    )

    assert restored.schema_version == 1
    assert restored.query.agents == ["build.*"]
    assert restored.query.key_limit == 0
    assert restored.groups[0].values[0].agents == ["build", "build.worker"]
    assert restored.groups[0].values[0].newest.timestamp == "20260814111111"


def test_query_agent_output_variable_history_calls_rust_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_query(index_path: str, query: dict[str, Any]) -> dict[str, Any]:
        calls.append((index_path, query))
        return {
            "schema_version": 1,
            "index_path": index_path,
            "query": query,
            "keys_limit": {
                "limit": query["key_limit"],
                "total_count": 0,
                "returned_count": 0,
                "truncated": False,
            },
            "groups": [],
        }

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding",
        lambda name: (
            fake_query
            if name == "query_agent_output_variable_history"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    index = tmp_path / "agent_artifact_index.sqlite"
    history = query_agent_output_variable_history(
        index,
        AgentOutputVariableHistoryQueryWire(keys=["status"], key_limit=4),
    )

    assert calls[0][0] == str(index)
    assert calls[0][1]["keys"] == ["status"]
    assert calls[0][1]["key_limit"] == 4
    assert history.groups == []
    assert history.keys_limit.total_count == 0
