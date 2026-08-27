from __future__ import annotations

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVacuumWire,
    AgentArtifactIndexWindowWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_status_from_dict,
    agent_artifact_index_update_from_dict,
    agent_artifact_index_vacuum_from_dict,
    agent_scan_wire_from_dict,
)


def test_artifact_index_wire_helpers() -> None:
    assert AgentArtifactIndexQueryWire().active_limit is None
    assert AgentArtifactIndexQueryWire().freshness == "revalidate"
    assert AgentArtifactIndexQueryWire().record_shape == "full"

    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=False,
        include_full_history=True,
        active_limit=50,
        recent_completed_limit=None,
        include_hidden=True,
        freshness="cached",
        only_monitors=True,
        record_shape="list",
        window_limit=75,
        candidate_filter={
            "kind": "contains",
            "field": "project",
            "value": "sase",
        },
    )
    assert agent_artifact_index_query_to_dict(query) == {
        "include_active": True,
        "include_recent_completed": False,
        "include_full_history": True,
        "active_limit": 50,
        "recent_completed_limit": None,
        "include_hidden": True,
        "freshness": "cached",
        "only_monitors": True,
        "record_shape": "list",
        "window_limit": 75,
        "candidate_filter": {
            "kind": "contains",
            "field": "project",
            "value": "sase",
        },
    }
    assert AgentArtifactIndexQueryWire().only_monitors is False

    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [],
            "clan_context": [],
            "index_window": {
                "requested_limit": 75,
                "selected_candidate_count": 30,
                "returned_record_count": 28,
                "active_candidate_count": 8,
                "completed_candidate_count": 22,
                "has_more": True,
                "truncated": True,
            },
        }
    )
    assert snapshot.index_window == AgentArtifactIndexWindowWire(
        requested_limit=75,
        selected_candidate_count=30,
        returned_record_count=28,
        active_candidate_count=8,
        completed_candidate_count=22,
        has_more=True,
        truncated=True,
    )

    update = agent_artifact_index_update_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "rows_indexed": 2,
            "rows_deleted": 1,
            "rows_skipped": 3,
            "hidden_terminal_rows_retained": 4,
            "hidden_terminal_rows_pruned": 5,
        }
    )
    assert update == AgentArtifactIndexUpdateWire(
        schema_version=1,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        rows_indexed=2,
        rows_deleted=1,
        rows_skipped=3,
        hidden_terminal_rows_retained=4,
        hidden_terminal_rows_pruned=5,
    )

    status = agent_artifact_index_status_from_dict(
        {
            "schema_version": 4,
            "index_path": "/tmp/index.sqlite",
            "agent_artifacts_rows": 10,
            "agent_artifact_aliases_rows": 1,
            "dismissed_agents_rows": 2,
            "hidden_terminal_retention_limit": 4096,
            "hidden_terminal_rows_retained": 3,
            "hidden_terminal_rows_prunable": 4,
            "freelist_pages": 6,
            "freelist_bytes": 24576,
            "file_size_bytes": 1048576,
        }
    )
    assert status == AgentArtifactIndexStatusWire(
        schema_version=4,
        index_path="/tmp/index.sqlite",
        agent_artifacts_rows=10,
        agent_artifact_aliases_rows=1,
        dismissed_agents_rows=2,
        hidden_terminal_retention_limit=4096,
        hidden_terminal_rows_retained=3,
        hidden_terminal_rows_prunable=4,
        freelist_pages=6,
        freelist_bytes=24576,
        file_size_bytes=1048576,
    )


def test_artifact_index_vacuum_wire_round_trips() -> None:
    update = agent_artifact_index_vacuum_from_dict(
        {
            "index_path": "/tmp/index.sqlite",
            "freelist_pages_before": 6,
            "freelist_pages_after": 0,
            "file_size_bytes_before": 1048576,
            "file_size_bytes_after": 1024000,
            "bytes_reclaimed": 24576,
        }
    )
    assert update == AgentArtifactIndexVacuumWire(
        index_path="/tmp/index.sqlite",
        freelist_pages_before=6,
        freelist_pages_after=0,
        file_size_bytes_before=1048576,
        file_size_bytes_after=1024000,
        bytes_reclaimed=24576,
    )
