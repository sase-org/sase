"""Single fan-out entry point over every artifact-link projection rule."""

from __future__ import annotations

from typing import Any

from sase.artifact_links.projection._agent_bead import project_agent_bead_rows
from sase.artifact_links.projection._chop_agent import project_chop_agent_rows
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs
from sase.artifact_links.projection._stitch_rules import project_stitch_rules
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION

_DESCRIPTION_MAX_LENGTH = 240


def project_link_rows(inputs: ProjectionInputs) -> tuple[dict[str, Any], ...]:
    """Run every projection rule and return materialized `origin: projected` rows.

    Writes nothing itself: the caller owns persistence. Each rule is
    independently best-effort, so one rule's failure never suppresses
    another's rows.
    """

    edges: list[ProjectedEdge] = []
    edges.extend(project_stitch_rules(inputs))
    edges.extend(project_agent_bead_rows(inputs))
    edges.extend(project_chop_agent_rows(inputs))
    return tuple(_row_from_edge(edge) for edge in edges)


def _row_from_edge(edge: ProjectedEdge) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": edge.source_ref,
        "relation": edge.relation,
        "target_ref": edge.target_ref,
        "description": edge.description[:_DESCRIPTION_MAX_LENGTH],
        "origin": "projected",
        "created_by": f"projection:{edge.rule_id}",
        "created_at": edge.created_at,
        "uses": 1,
    }


__all__ = ["project_link_rows"]
