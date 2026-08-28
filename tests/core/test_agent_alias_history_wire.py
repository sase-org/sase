"""Tests for the Python alias-history wire and facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_alias_history_wire import (
    AGENT_ALIAS_HISTORY_WIRE_SCHEMA_VERSION,
    AgentAliasHistoryQueryWire,
    agent_alias_history_from_dict,
    agent_alias_history_query_to_dict,
)
from sase.core.agent_scan_facade import query_agent_alias_history
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION


def test_alias_history_schema_versions_are_pinned() -> None:
    assert AGENT_ALIAS_HISTORY_WIRE_SCHEMA_VERSION == 1
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 25


def test_alias_history_query_round_trips_defaults_and_filters() -> None:
    query = AgentAliasHistoryQueryWire(
        aliases=["large", "coder"],
        limit_per_alias=0,
        include_hidden=True,
        projects=["sase"],
        prompt_snippet_bytes=0,
        freshness="revalidate",
    )

    payload = agent_alias_history_query_to_dict(query)
    assert payload == {
        "aliases": ["large", "coder"],
        "limit_per_alias": 0,
        "include_hidden": True,
        "projects": ["sase"],
        "prompt_snippet_bytes": 0,
        "freshness": "revalidate",
    }

    restored = agent_alias_history_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "query": payload,
            "groups": [
                {
                    "alias": "large",
                    "runs_limit": {
                        "limit": 0,
                        "total_count": 1,
                        "returned_count": 1,
                        "truncated": False,
                    },
                    "runs": [
                        {
                            "artifact_dir": "/tmp/a",
                            "project_name": "sase",
                            "workflow_dir_name": "ace-run",
                            "timestamp": "20260816120000",
                            "alias_position": 1,
                            "status": "completed",
                            "has_done_marker": True,
                            "hidden": False,
                            "agent_name": "worker",
                            "model": "claude-opus",
                            "llm_provider": "claude",
                            "reasoning_effort": "high",
                            "model_alias": "coder",
                            "model_alias_origin": "directive",
                            "model_alias_trail": ["coder", "large"],
                            "bead_id": "sase-n8.3",
                            "workspace_num": 15,
                            "prompt_snippet": "Refactor the module",
                            "used_xprompts": [{"name": "gh:sase", "kind": "reference"}],
                        }
                    ],
                },
                {
                    "alias": "coder",
                    "runs_limit": {
                        "limit": 0,
                        "total_count": 0,
                        "returned_count": 0,
                        "truncated": False,
                    },
                    "runs": [],
                },
            ],
        }
    )

    assert restored.schema_version == 1
    assert restored.query.aliases == ["large", "coder"]
    assert restored.query.freshness == "revalidate"
    assert len(restored.groups) == 2
    run = restored.groups[0].runs[0]
    assert run.alias_position == 1
    assert run.model_alias_trail == ["coder", "large"]
    assert run.model_alias_origin == "directive"
    assert run.used_xprompts[0].name == "gh:sase"
    assert restored.groups[1].runs == []


def test_alias_history_from_dict_tolerates_unknown_keys() -> None:
    restored = agent_alias_history_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "query": {"aliases": ["large"], "future_field": "ignored"},
            "future_top_level_field": True,
            "groups": [
                {
                    "alias": "large",
                    "runs_limit": {
                        "limit": 10,
                        "total_count": 1,
                        "returned_count": 1,
                        "truncated": False,
                    },
                    "runs": [
                        {
                            "artifact_dir": "/tmp/a",
                            "project_name": "sase",
                            "workflow_dir_name": "ace-run",
                            "timestamp": "20260816120000",
                            "alias_position": 0,
                            "status": "completed",
                            "has_done_marker": True,
                            "hidden": False,
                            "future_run_field": "ignored",
                        }
                    ],
                    "future_group_field": "ignored",
                }
            ],
        }
    )

    assert restored.query.aliases == ["large"]
    run = restored.groups[0].runs[0]
    assert run.alias_position == 0
    assert run.model_alias_trail == []
    assert run.model_alias_origin is None
    assert run.used_xprompts == []


def test_query_agent_alias_history_takes_lock_and_converts_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _FakeLock:
        def __enter__(self) -> None:
            calls.append("lock-enter")

        def __exit__(self, *_args: object) -> None:
            calls.append("lock-exit")

    def fake_lock() -> _FakeLock:
        return _FakeLock()

    def fake_query(index_path: str, query: dict[str, Any]) -> dict[str, Any]:
        calls.append("rust-query")
        return {
            "schema_version": 1,
            "index_path": index_path,
            "query": query,
            "groups": [
                {
                    "alias": query["aliases"][0],
                    "runs_limit": {
                        "limit": query["limit_per_alias"],
                        "total_count": 0,
                        "returned_count": 0,
                        "truncated": False,
                    },
                    "runs": [],
                }
            ],
        }

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.agent_artifact_index_operation_lock",
        fake_lock,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding",
        lambda name: (
            fake_query
            if name == "query_agent_alias_history"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    index = tmp_path / "agent_artifact_index.sqlite"
    history = query_agent_alias_history(
        index,
        AgentAliasHistoryQueryWire(aliases=["large"], limit_per_alias=5),
    )

    assert calls == ["lock-enter", "rust-query", "lock-exit"]
    assert history.groups[0].alias == "large"
    assert history.groups[0].runs_limit.limit == 5
