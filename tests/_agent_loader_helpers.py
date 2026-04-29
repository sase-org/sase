"""Test helpers for the snapshot-aware agent loader code path."""

from __future__ import annotations

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)


def _empty_artifact_snapshot() -> AgentArtifactScanWire:
    """Return a no-records snapshot suitable for mocking the TUI loader scan."""
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )
