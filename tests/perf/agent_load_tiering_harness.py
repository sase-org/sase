"""Synthetic archive and parity oracle for Agents-tab load tiering.

The ``sase-zu`` epic changes how the Agents tab chooses artifact load
tiers. This module gives later phases a shared, real-file fixture and a
small oracle that compares loader-visible row sets across the current
source scan, bounded artifact-index query, and full-history artifact-index
query paths.

The fixture writes production-shaped marker files rather than wire objects
so the Rust scanner, SQLite index rebuild, index query, and Python
snapshot-to-Agent projection all run on their real interfaces. A few rows
carry imported-owner/source-machine provenance in marker JSON so later
phases can exercise the indexed machine candidate field.
"""

from __future__ import annotations

from tests.perf._agent_load_tiering_benchmark import benchmark_load_paths
from tests.perf._agent_load_tiering_oracle import AgentLoadTieringOracle
from tests.perf._agent_load_tiering_types import (
    AgentLoadTieringOracleResult,
    LoadPathDiff,
    LoadPathRows,
    QUERY_BATTERY,
    QueryBatteryCase,
    VisibleAgentRow,
)
from tests.perf.agent_load_tiering_fixture import (
    DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    SyntheticArchiveFixture,
    build_synthetic_agent_archive,
)

__all__ = [
    "AgentLoadTieringOracle",
    "AgentLoadTieringOracleResult",
    "DEFAULT_ARCHIVE_ARTIFACT_COUNT",
    "LoadPathDiff",
    "LoadPathRows",
    "QUERY_BATTERY",
    "QueryBatteryCase",
    "SyntheticArchiveFixture",
    "VisibleAgentRow",
    "benchmark_load_paths",
    "build_synthetic_agent_archive",
]
