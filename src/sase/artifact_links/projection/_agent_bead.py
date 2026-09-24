"""Project `implements` rows from published agent metadata's bead fields."""

from __future__ import annotations

from sase.agents_sync.v2_models import V2RunMetadataPayload
from sase.artifact_links.projection._agent_meta_scan import project_agent_meta_rows
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs

_RULE_ID = "agent-bead"
_BEAD_METADATA_FIELDS = ("bead_id", "epic_bead_id", "phase_bead_id")


def project_agent_bead_rows(inputs: ProjectionInputs) -> tuple[ProjectedEdge, ...]:
    """Emit one row per non-empty bead field in a published agent's meta.json."""

    return project_agent_meta_rows(
        inputs, rule_id=_RULE_ID, rows_for_metadata=_rows_for_metadata
    )


def _rows_for_metadata(
    metadata: V2RunMetadataPayload, created_at: str
) -> list[dict[str, str]]:
    fields = dict(metadata.metadata)
    rows: list[dict[str, str]] = []
    for field_name in _BEAD_METADATA_FIELDS:
        value = fields.get(field_name)
        if not isinstance(value, str) or not value.strip():
            continue
        bead_id = value.strip()
        rows.append(
            {
                "source_ref": f"agent:{metadata.global_name}",
                "relation": "implements",
                "target_ref": f"bead:{bead_id}",
                "description": (
                    f"published meta.json's `{field_name}` field names bead {bead_id}"
                ),
                "created_at": created_at,
            }
        )
    return rows


__all__ = ["project_agent_bead_rows"]
