from __future__ import annotations

import pytest

from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    agent_scan_wire_from_dict,
)

from .agent_scan_golden import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
    fixture_summary,
)


def test_schema_version_pinned() -> None:
    """Bumping the schema is a deliberate, reviewable event."""
    assert AGENT_SCAN_WIRE_SCHEMA_VERSION == 7
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 25


def test_scan_wire_rejects_stale_binding_schema() -> None:
    with pytest.raises(ValueError, match="schema mismatch"):
        agent_scan_wire_from_dict(
            {
                "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION - 1,
                "projects_root": "/tmp/projects",
                "records": [],
            }
        )


def test_fixture_summary_matches_expectations() -> None:
    """Pin the fixture's surface area so adding a branch forces a test update."""
    summary = fixture_summary()
    assert summary["timestamps"] == list(EXPECTED_TIMESTAMPS)
    assert summary["expected_decode_errors"] == EXPECTED_DECODE_ERRORS
    assert summary["expected_os_errors"] == EXPECTED_OS_ERRORS
