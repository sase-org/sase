from __future__ import annotations

from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexUpdateWire,
    DismissedAgentIdentityWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_update_from_dict,
    dismissed_agent_identity_to_dict,
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
    # Phase 2 of sase-3r introduced the dismissed_agents sidecar table.
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 2


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
        # Default for back-compat with Phase 1 callers.
        "include_dismissed": True,
    }

    update = agent_artifact_index_update_from_dict(
        {
            "schema_version": 2,
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "rows_indexed": 2,
            "rows_deleted": 1,
            "rows_skipped": 3,
        }
    )
    assert update == AgentArtifactIndexUpdateWire(
        schema_version=2,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        rows_indexed=2,
        rows_deleted=1,
        rows_skipped=3,
    )


def test_inbox_query_passes_include_dismissed_false() -> None:
    """Phase 3 will pass ``include_dismissed=False`` to get the inbox view."""

    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        recent_completed_limit=None,
        include_hidden=False,
        include_dismissed=False,
    )
    payload = agent_artifact_index_query_to_dict(query)
    assert payload["include_dismissed"] is False
    assert payload["include_active"] is True
    assert payload["recent_completed_limit"] is None


def test_dismissed_agent_identity_to_dict_roundtrip() -> None:
    identity = DismissedAgentIdentityWire(
        agent_type="run",
        cl_name="cl_alpha",
        raw_suffix="20260516120000",
        dismissed_at="2026-05-16T12:00:00Z",
    )
    assert dismissed_agent_identity_to_dict(identity) == {
        "agent_type": "run",
        "cl_name": "cl_alpha",
        "raw_suffix": "20260516120000",
        "dismissed_at": "2026-05-16T12:00:00Z",
    }

    # ``raw_suffix=None`` represents the legacy "every suffix in this
    # (agent_type, cl_name) prefix" entry and is passed through verbatim;
    # the Rust binding maps it to the empty-string sentinel for storage.
    whole_identity = DismissedAgentIdentityWire(
        agent_type="workflow",
        cl_name="cl_beta",
    )
    assert dismissed_agent_identity_to_dict(whole_identity) == {
        "agent_type": "workflow",
        "cl_name": "cl_beta",
        "raw_suffix": None,
        "dismissed_at": None,
    }


def test_fixture_summary_matches_expectations() -> None:
    """Pin the fixture's surface area so adding a branch forces a test update."""
    summary = fixture_summary()
    assert summary["timestamps"] == list(EXPECTED_TIMESTAMPS)
    assert summary["expected_decode_errors"] == EXPECTED_DECODE_ERRORS
    assert summary["expected_os_errors"] == EXPECTED_OS_ERRORS
