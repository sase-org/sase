"""Thin Python facade for targeted agent-artifact identity lookups.

Healthy lookups take the process-local index lock with a 50ms budget, then
delegate matching to ``sase_core_rs.lookup_agent_artifacts``. A busy lock
forces the shared bounded recovery path instead of waiting on maintenance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lock import (
    DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
    try_agent_artifact_index_operation_lock,
)
from sase.core.agent_artifact_lookup_wire import (
    AgentArtifactLookupQueryWire,
    AgentArtifactLookupResultWire,
    agent_artifact_lookup_query_to_dict,
    agent_artifact_lookup_result_from_dict,
)
from sase.core.index_lookup_patience import retry_while_busy
from sase.core.rust import require_rust_binding


def lookup_agent_artifacts(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactLookupQueryWire,
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> AgentArtifactLookupResultWire:
    """Look up matching ace-run artifacts without maintenance on the read path."""
    payload = agent_artifact_lookup_query_to_dict(query)

    def attempt() -> AgentArtifactLookupResultWire:
        with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
            attempt_payload = (
                payload if acquired else {**payload, "forced_unavailability": "busy"}
            )
            rust_lookup = require_rust_binding("lookup_agent_artifacts")
            result: dict[str, Any] = rust_lookup(
                str(index_path),
                str(projects_root),
                attempt_payload,
            )
        return agent_artifact_lookup_result_from_dict(result)

    return retry_while_busy(
        attempt,
        is_busy=lambda result: result.availability == "busy" and not result.complete,
        diagnostic=lambda result: result.diagnostic,
        lookup="agent artifact index",
    )


__all__ = ["lookup_agent_artifacts"]
