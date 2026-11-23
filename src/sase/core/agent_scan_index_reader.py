"""Consumer-owned decoded records, validated by the native index on every read."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core._agent_scan_shared import options_to_dict
from sase.core.agent_artifact_index_lock import (
    agent_artifact_index_operation_lock,
    try_agent_artifact_index_operation_lock,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
    agent_artifact_index_query_to_dict,
    agent_scan_wire_from_dict,
)
from sase.core.rust import require_rust_binding


class AgentArtifactIndexReader:
    """One read-only consumer's last full-record payload.

    Rust owns query identity, invalidation, and generation allocation. This
    adapter retains at most one decoded record list and never skips a native
    query. Metadata, repair counters, and clan context are decoded every time.

    Returned records belong to this reader and must not be mutated. Independent
    consumers use independent readers. Callers needing fresh mutable values use
    the established ``query_agent_artifact_index`` API instead. There are no
    binding-owned Python handles or process-global Python result caches.
    """

    def __init__(self) -> None:
        self._generation: int | None = None
        self._records: list[AgentArtifactRecordWire] = []

    def query(
        self,
        index_path: Path | str,
        projects_root: Path | str,
        query: AgentArtifactIndexQueryWire | None = None,
        options: AgentArtifactScanOptionsWire | None = None,
        *,
        lock_timeout_seconds: float | None = None,
    ) -> AgentArtifactScanWire | None:
        """Revalidate records; return ``None`` only if the bounded lock is busy."""
        if lock_timeout_seconds is None:
            with agent_artifact_index_operation_lock():
                return self._read(index_path, projects_root, query, options)
        with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
            if not acquired:
                return None
            return self._read(index_path, projects_root, query, options)

    def _read(
        self,
        index_path: Path | str,
        projects_root: Path | str,
        query: AgentArtifactIndexQueryWire | None,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        try:
            binding = require_rust_binding("query_agent_artifact_index_reusable")
            payload: dict[str, Any] = binding(
                str(index_path),
                str(projects_root),
                agent_artifact_index_query_to_dict(
                    query or AgentArtifactIndexQueryWire()
                ),
                options_to_dict(options or AgentArtifactScanOptionsWire()),
                self._generation,
            )
            generation = payload.get("payload_generation")
            snapshot = agent_scan_wire_from_dict(payload["snapshot"])
            if payload["records_reused"]:
                if (
                    generation is None
                    or generation != self._generation
                    or snapshot.records
                ):
                    raise ValueError("invalid native artifact-index reuse response")
                snapshot = replace(snapshot, records=self._records)
            self._generation = generation
            self._records = snapshot.records
            return snapshot
        except BaseException:
            # A failed binding/decoder never installs or certifies a generation.
            self._generation = None
            self._records = []
            raise
