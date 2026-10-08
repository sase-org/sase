"""Single fan-out entry point over every artifact-link projection rule."""

from __future__ import annotations

import logging
from typing import Any

from sase.artifact_links.projection._agent_bead import project_agent_bead_rows
from sase.artifact_links.projection._agent_wait_bead import (
    project_agent_wait_bead_rows,
)
from sase.artifact_links.projection._chop_agent import project_chop_agent_rows
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs
from sase.artifact_links.projection._stitch_rules import project_stitch_rules
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    canonicalize_artifact_link_ref,
)

_DESCRIPTION_MAX_LENGTH = 240

_logger = logging.getLogger(__name__)


def project_link_rows(inputs: ProjectionInputs) -> tuple[dict[str, Any], ...]:
    """Run every projection rule and return materialized `origin: projected` rows.

    Writes nothing itself: the caller owns persistence. Each rule is
    independently best-effort, so one rule's failure never suppresses
    another's rows. Edges whose endpoints fail ref validation are dropped
    here so one malformed row can never reach the machine-local aggregate.
    """

    # Imported lazily to keep the TUI startup closure lean.
    from sase.artifact_links.projection._agent_created_epic import (
        project_agent_created_epic_attributed_rows,
        project_agent_created_epic_rows,
    )

    edges: list[ProjectedEdge] = []
    edges.extend(project_stitch_rules(inputs))
    edges.extend(project_agent_bead_rows(inputs))
    edges.extend(project_agent_created_epic_rows(inputs))
    edges.extend(project_agent_created_epic_attributed_rows(inputs))
    edges.extend(project_agent_wait_bead_rows(inputs))
    edges.extend(project_chop_agent_rows(inputs))
    return tuple(_row_from_edge(edge) for edge in edges if _edge_refs_valid(edge))


def _edge_refs_valid(edge: ProjectedEdge) -> bool:
    """Return whether both endpoint refs of *edge* validate.

    The refs are checked but never rewritten, so emitted row identities
    and dedup behavior do not change for valid edges.
    """

    for ref in (edge.source_ref, edge.target_ref):
        try:
            canonicalize_artifact_link_ref(ref)
        except (ValueError, TypeError):
            _logger.warning(
                "dropping projected edge with invalid ref: rule=%s ref=%r",
                edge.rule_id,
                ref,
            )
            return False
    return True


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
