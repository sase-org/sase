"""Production-shaped synthetic agent archives for load-tier benchmarks."""

from __future__ import annotations

from tests.perf._agent_load_tiering_fixture_build import (
    build_synthetic_agent_archive,
    rebuild_index,
)
from tests.perf._agent_load_tiering_fixture_core import (
    DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    SyntheticArchiveFixture,
)
from tests.perf._agent_load_tiering_fixture_mutations import (
    delete_artifact,
    set_artifact_hidden,
    set_artifact_machine_provenance,
    write_completed_artifact,
    write_waiting_artifact,
)

__all__ = [
    "DEFAULT_ARCHIVE_ARTIFACT_COUNT",
    "SyntheticArchiveFixture",
    "build_synthetic_agent_archive",
    "delete_artifact",
    "rebuild_index",
    "set_artifact_hidden",
    "write_completed_artifact",
    "write_waiting_artifact",
]
