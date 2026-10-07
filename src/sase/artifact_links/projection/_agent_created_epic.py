"""Project `produced-by` rows from recorded epic launches.

Two rules emit the same `bead:<epic> produced-by agent:<creator>` edge from
two evidence sources, so unpublished planners get the edge too:

- ``agent-created-epic`` reads the portable ``created_epic_ids`` list the
  creator published in its agent ``meta.json`` (recorded under a lock by
  ``sase bead work``);
- ``agent-created-epic-attributed`` falls back to bead-store attribution:
  epic-tier plan beads whose ``created_by`` names an agent.

Both rules stay best-effort: an unreadable store or unparseable row only
drops that rule's rows. Neither rule fires for a worker's inherited epic,
because that ID never appears in ``created_epic_ids`` and a worker is never
its parent epic's ``created_by``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agents_sync.v2_models import V2RunMetadataPayload
from sase.artifact_links.projection._agent_meta_scan import project_agent_meta_rows
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs

_RULE_ID_METADATA = "agent-created-epic"
_RULE_ID_ATTRIBUTED = "agent-created-epic-attributed"


def project_agent_created_epic_rows(
    inputs: ProjectionInputs,
) -> tuple[ProjectedEdge, ...]:
    """Emit one `produced-by` row per published `created_epic_ids` entry."""

    return project_agent_meta_rows(
        inputs, rule_id=_RULE_ID_METADATA, rows_for_metadata=_rows_for_metadata
    )


def _rows_for_metadata(
    metadata: V2RunMetadataPayload, created_at: str
) -> list[dict[str, str]]:
    fields = dict(metadata.metadata)
    raw_value: Any = fields.get("created_epic_ids")
    if not isinstance(raw_value, list):
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_value:
        if not isinstance(item, str):
            continue
        bead_id = item.strip()
        if not bead_id or bead_id in seen:
            continue
        if any(char.isspace() for char in bead_id):
            continue
        seen.add(bead_id)
        rows.append(
            {
                "source_ref": f"bead:{bead_id}",
                "relation": "produced-by",
                "target_ref": f"agent:{metadata.global_name}",
                "description": (
                    f"published meta.json's `created_epic_ids` names epic {bead_id}"
                ),
                "created_at": created_at,
            }
        )
    return rows


def project_agent_created_epic_attributed_rows(
    inputs: ProjectionInputs,
) -> tuple[ProjectedEdge, ...]:
    """Emit the same edge from bead-store attribution for unpublished planners."""

    if inputs.bead_store_root is None:
        return ()
    try:
        issues = _epic_plan_issues(inputs.bead_store_root)
    except Exception:  # noqa: BLE001 - an unreadable store contributes no rows.
        return ()
    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    edges: list[ProjectedEdge] = []
    for issue in issues:
        bead_id = getattr(issue, "id", "")
        creator = getattr(issue, "created_by", "")
        if not isinstance(bead_id, str) or not bead_id.strip():
            continue
        if any(char.isspace() for char in bead_id):
            continue
        if not _is_agent_creator(creator):
            continue
        creator_name = creator.strip()
        edges.append(
            ProjectedEdge(
                source_ref=f"bead:{bead_id.strip()}",
                relation="produced-by",
                target_ref=f"agent:{creator_name}",
                description=(
                    f"epic {bead_id.strip()} names agent {creator_name} as creator"
                ),
                rule_id=_RULE_ID_ATTRIBUTED,
                created_at=created_at,
            )
        )
    return tuple(edges)


def _epic_plan_issues(beads_dir: Path) -> list[Any]:
    from sase.bead.model import BeadTier, IssueType
    from sase.bead.store_locator import open_bead_project_for_beads_dir

    with open_bead_project_for_beads_dir(beads_dir) as bead_project:
        return bead_project.list_issues(
            issue_types=[IssueType.PLAN],
            tiers=[BeadTier.EPIC],
        )


def _is_agent_creator(value: object) -> bool:
    """Return whether *value* plausibly names the agent that launched an epic.

    Agent global and session names are dotted single tokens, while
    human-filed backlog epics carry the store-owner email (which contains
    ``@``) or a bare username (no dot), so both are excluded. Deliberately
    best-effort: a stray edge is cheaper than a missing one here, and the
    entry point still drops refs that fail validation.
    """

    if not isinstance(value, str):
        return False
    token = value.strip()
    if not token or "@" in token:
        return False
    if any(char.isspace() for char in token):
        return False
    return "." in token


__all__ = [
    "project_agent_created_epic_attributed_rows",
    "project_agent_created_epic_rows",
]
