"""Provider-neutral artifact metadata helpers for agent marker files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ARTIFACT_AGENT_METADATA_SCHEMA_VERSION = 1


def _fallback_agent_artifact_id(artifacts_dir: str) -> str:
    """Return the deterministic fallback graph ID for an agent artifacts dir."""
    project, workflow, timestamp = _artifact_identity_parts(artifacts_dir)
    return f"agent:{project}:{workflow}:{timestamp}"


def enrich_agent_artifact_metadata(
    metadata: dict[str, Any],
    *,
    artifacts_dir: str,
    agent_name: str | None = None,
    cl_name: str | None = None,
    bead_id: str | None = None,
    parent_agent_timestamp: str | None = None,
    parent_agent_name: str | None = None,
) -> dict[str, Any]:
    """Add stable artifact graph identity fields to an agent metadata dict.

    Existing marker fields are preserved. The helper only augments the
    provider-neutral contract that graph ingestion can rely on across runtimes.
    """
    enriched = dict(metadata)
    source_dir = str(Path(artifacts_dir).expanduser())
    stable_name = _non_empty(agent_name) or _non_empty(enriched.get("name"))

    enriched["artifact_schema_version"] = ARTIFACT_AGENT_METADATA_SCHEMA_VERSION
    enriched["artifact_source_dir"] = source_dir
    enriched["artifact_agent_id"] = stable_name or _fallback_agent_artifact_id(
        artifacts_dir
    )

    changespec_name = _non_empty(cl_name) or _non_empty(enriched.get("cl_name"))
    if changespec_name:
        enriched["changespec_name"] = changespec_name
        enriched.setdefault("cl_name", changespec_name)

    if _non_empty(bead_id):
        enriched["bead_id"] = bead_id

    parent_timestamp = _non_empty(parent_agent_timestamp)
    if parent_timestamp:
        enriched["parent_agent_timestamp"] = parent_timestamp
    parent_name = _non_empty(parent_agent_name)
    if parent_name:
        enriched["parent_agent_name"] = parent_name

    return enriched


def write_agent_artifact_metadata(
    artifacts_dir: str,
    metadata: dict[str, Any],
    *,
    agent_name: str | None = None,
    cl_name: str | None = None,
    bead_id: str | None = None,
    parent_agent_timestamp: str | None = None,
    parent_agent_name: str | None = None,
) -> dict[str, Any]:
    """Enrich and write ``agent_meta.json`` in one step."""
    enriched = enrich_agent_artifact_metadata(
        metadata,
        artifacts_dir=artifacts_dir,
        agent_name=agent_name,
        cl_name=cl_name,
        bead_id=bead_id,
        parent_agent_timestamp=parent_agent_timestamp,
        parent_agent_name=parent_agent_name,
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    return enriched


def _artifact_identity_parts(artifacts_dir: str) -> tuple[str, str, str]:
    path = Path(artifacts_dir).expanduser()
    parts = path.parts
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] != "artifacts":
            continue
        if index > 0 and index + 2 < len(parts):
            return parts[index - 1], parts[index + 1], parts[index + 2]

    timestamp = path.name or "unknown"
    workflow = path.parent.name or "unknown"
    project = os.environ.get("SASE_PROJECT_NAME") or "unknown"
    return project, workflow, timestamp


def _non_empty(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
