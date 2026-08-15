"""Tests for the Python output-variable selector wire and facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_output_variable_selector_wire import (
    AGENT_OUTPUT_VARIABLE_SELECTOR_WIRE_SCHEMA_VERSION,
    AgentOutputVariableSelectorQueryWire,
    OutputVariableSelectorPathWire,
    OutputVariableSelectorWire,
    _OutputVariableSelectorScopeWire,
    agent_output_variable_selector_query_to_dict,
    agent_output_variable_selector_result_from_dict,
)
from sase.core.agent_scan_facade import (
    parse_output_variable_selector,
    query_agent_output_variable_selectors,
)


def test_selector_schema_version_is_pinned() -> None:
    assert AGENT_OUTPUT_VARIABLE_SELECTOR_WIRE_SCHEMA_VERSION == 1


def test_selector_query_round_trips() -> None:
    query = AgentOutputVariableSelectorQueryWire(
        selectors=[
            OutputVariableSelectorWire(
                raw='build.report["summary"]',
                scope=_OutputVariableSelectorScopeWire(kind="exact", name="build"),
                key="report",
                path=[OutputVariableSelectorPathWire(kind="key", key="summary")],
            )
        ],
        projects=["sase"],
        include_hidden=True,
        limit=0,
    )
    payload = agent_output_variable_selector_query_to_dict(query)
    restored = agent_output_variable_selector_result_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "query": payload,
            "matches_limit": {
                "limit": 0,
                "total_count": 1,
                "returned_count": 1,
                "truncated": False,
            },
            "matches": [
                {
                    "selector": 'build.report["summary"]',
                    "key": "report",
                    "path": [{"kind": "key", "key": "summary"}],
                    "value": "ok",
                    "value_json": '"ok"',
                    "artifact_dir": "/tmp/a",
                    "project_name": "sase",
                    "workflow_dir_name": "ace-run",
                    "timestamp": "20260815121212",
                    "agent_name": "build",
                    "cl_name": "sase",
                    "hidden": False,
                }
            ],
        }
    )

    assert restored.query.limit == 0
    assert restored.query.selectors[0].scope.name == "build"
    assert restored.matches[0].value == "ok"
    assert restored.matches[0].path[0].key == "summary"


def test_parse_and_query_call_rust_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_calls: list[str] = []
    query_calls: list[tuple[str, dict[str, Any]]] = []

    def fake_parse(selector: str) -> dict[str, Any]:
        parsed_calls.append(selector)
        return {
            "raw": selector,
            "scope": {"kind": "unscoped"},
            "key": selector,
            "path": [],
        }

    def fake_query(index_path: str, query: dict[str, Any]) -> dict[str, Any]:
        query_calls.append((index_path, query))
        return {
            "schema_version": 1,
            "index_path": index_path,
            "query": query,
            "matches_limit": {
                "limit": query["limit"],
                "total_count": 0,
                "returned_count": 0,
                "truncated": False,
            },
            "matches": [],
        }

    def fake_binding(name: str) -> object:
        if name == "parse_output_variable_selector":
            return fake_parse
        if name == "query_agent_output_variable_selectors":
            return fake_query
        raise AssertionError(name)

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding",
        fake_binding,
    )

    selector = parse_output_variable_selector("status")
    index = tmp_path / "agent_artifact_index.sqlite"
    result = query_agent_output_variable_selectors(
        index,
        AgentOutputVariableSelectorQueryWire(selectors=[selector], limit=4),
    )

    assert parsed_calls == ["status"]
    assert query_calls[0][0] == str(index)
    assert query_calls[0][1]["limit"] == 4
    assert query_calls[0][1]["selectors"][0]["raw"] == "status"
    assert result.matches == []
    assert result.matches_limit.total_count == 0
