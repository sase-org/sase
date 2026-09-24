"""Project `awaits` rows from published agent metadata's bead waits."""

from __future__ import annotations

from typing import Any

from sase.agents_sync.v2_models import V2RunMetadataPayload
from sase.artifact_links.projection._agent_meta_scan import project_agent_meta_rows
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs

_RULE_ID = "agent-wait-bead"


def project_agent_wait_bead_rows(
    inputs: ProjectionInputs,
) -> tuple[ProjectedEdge, ...]:
    """Emit one `awaits` row per distinct bead id in `wait_for_beads`."""

    return project_agent_meta_rows(
        inputs, rule_id=_RULE_ID, rows_for_metadata=_rows_for_metadata
    )


def _rows_for_metadata(
    metadata: V2RunMetadataPayload, created_at: str
) -> list[dict[str, str]]:
    fields = dict(metadata.metadata)
    raw_value: Any = fields.get("wait_for_beads")
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
                "source_ref": f"agent:{metadata.global_name}",
                "relation": "awaits",
                "target_ref": f"bead:{bead_id}",
                "description": (
                    f"published meta.json's `wait_for_beads` names bead {bead_id}"
                ),
                "created_at": created_at,
            }
        )
    return rows


__all__ = ["project_agent_wait_bead_rows"]
