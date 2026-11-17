"""Thin facade for Rust-owned named-agent eligibility and ranking."""

from __future__ import annotations

from sase.core.agent_artifact_lookup_wire import (
    AgentArtifactLookupHitWire,
    NamedAgentObservationWire,
    NamedAgentSelectionResultWire,
    named_agent_selection_request_to_dict,
    named_agent_selection_result_from_dict,
)
from sase.core.rust import require_rust_binding


def select_named_agent(
    names: tuple[str, ...],
    hits: tuple[AgentArtifactLookupHitWire, ...],
    observations: tuple[NamedAgentObservationWire, ...],
    *,
    only_done: bool,
    include_dead: bool,
) -> NamedAgentSelectionResultWire:
    """Select one eligible hit using the shared Rust ranking contract."""
    request = named_agent_selection_request_to_dict(
        names,
        hits,
        observations,
        only_done=only_done,
        include_dead=include_dead,
    )
    result = require_rust_binding("select_named_agent")(request)
    if not isinstance(result, dict):
        raise RuntimeError("select_named_agent returned a non-object result")
    return named_agent_selection_result_from_dict(result)


__all__ = ["select_named_agent"]
