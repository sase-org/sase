"""Thin Rust facade for selecting indexed agent session and clan groups."""

from __future__ import annotations

from typing import Any

from sase.core.agent_artifact_lookup_wire import (
    AgentArtifactGroupSelectionQueryWire,
    AgentArtifactGroupSelectionResultWire,
    AgentArtifactLookupResultWire,
    agent_artifact_group_selection_query_to_dict,
    agent_artifact_group_selection_result_from_dict,
    agent_artifact_lookup_result_to_dict,
)
from sase.core.rust import require_rust_binding
from sase.core.index_lookup_errors import IndexLookupUnavailable


class AgentArtifactGroupLookupUnavailable(IndexLookupUnavailable):
    """A bounded lookup could not establish complete group membership."""

    def __init__(
        self,
        result: AgentArtifactGroupSelectionResultWire,
    ) -> None:
        details = [
            f"availability={result.availability}",
            f"source={result.source}",
        ]
        if result.diagnostic:
            details.append(result.diagnostic)
        super().__init__(
            "agent group lookup is incomplete (" + "; ".join(details) + ")",
            availability=result.availability,
            source=result.source,
            diagnostic=result.diagnostic,
            truncated=False,
        )
        self.result = result


def select_agent_artifact_group(
    lookup: AgentArtifactLookupResultWire,
    selection: AgentArtifactGroupSelectionQueryWire,
) -> AgentArtifactGroupSelectionResultWire:
    """Select a complete generation from one targeted lookup result."""
    rust_select = require_rust_binding("select_agent_artifact_group")
    result: dict[str, Any] = rust_select(
        agent_artifact_lookup_result_to_dict(lookup),
        agent_artifact_group_selection_query_to_dict(selection),
    )
    return agent_artifact_group_selection_result_from_dict(result)


def require_complete_group(
    result: AgentArtifactGroupSelectionResultWire,
) -> AgentArtifactGroupSelectionResultWire:
    """Reject partial groups so callers cannot mistake them for a miss."""
    if not result.complete:
        raise AgentArtifactGroupLookupUnavailable(result)
    return result


__all__ = [
    "AgentArtifactGroupLookupUnavailable",
    "require_complete_group",
    "select_agent_artifact_group",
]
