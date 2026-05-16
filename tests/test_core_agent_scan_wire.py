from __future__ import annotations

from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexUpdateWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_update_from_dict,
)

from .agent_scan_golden import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
    fixture_summary,
)


def test_schema_version_pinned() -> None:
    """Bumping the schema is a deliberate, reviewable event."""
    assert AGENT_SCAN_WIRE_SCHEMA_VERSION == 1
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 1


def test_artifact_index_wire_helpers() -> None:
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=False,
        include_full_history=True,
        recent_completed_limit=None,
        include_hidden=True,
    )
    assert agent_artifact_index_query_to_dict(query) == {
        "include_active": True,
        "include_recent_completed": False,
        "include_full_history": True,
        "recent_completed_limit": None,
        "include_hidden": True,
    }

    update = agent_artifact_index_update_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "rows_indexed": 2,
            "rows_deleted": 1,
            "rows_skipped": 3,
        }
    )
    assert update == AgentArtifactIndexUpdateWire(
        schema_version=1,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        rows_indexed=2,
        rows_deleted=1,
        rows_skipped=3,
    )


def test_fixture_summary_matches_expectations() -> None:
    """Pin the fixture's surface area so adding a branch forces a test update."""
    summary = fixture_summary()
    assert summary["timestamps"] == list(EXPECTED_TIMESTAMPS)
    assert summary["expected_decode_errors"] == EXPECTED_DECODE_ERRORS
    assert summary["expected_os_errors"] == EXPECTED_OS_ERRORS
