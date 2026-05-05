"""Provider-neutral artifact metadata helpers for agent marker files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ARTIFACT_AGENT_METADATA_SCHEMA_VERSION = 1
SASE_AGENT_WORKFLOW_LINKS_ENV = "SASE_AGENT_WORKFLOW_LINKS"

WORKFLOW_RELATIONSHIP_FIELDS = frozenset(
    {
        "plan_path",
        "sdd_prompt_path",
        "sdd_plan_path",
        "plan_submitted_at",
        "questions_submitted_at",
        "feedback_submitted_at",
        "question_request_path",
        "question_response_path",
        "question_session_id",
        "epic_bead_id",
        "phase_bead_id",
        "legend_bead_id",
        "bead_id",
        "commit_changespec_name",
        "commit_entry_id",
        "commit_result",
        "commit_diff_path",
        "changespec_name",
        "cl_name",
        "parent_agent_timestamp",
        "parent_agent_name",
        "source_plan_agent_name",
        "followup_agent_name",
    }
)


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


def enrich_agent_workflow_relationships(
    metadata: dict[str, Any],
    relationships: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add stable workflow relationship fields to marker metadata.

    This helper centralizes the additive fields used by plan, question,
    bead-work, and commit flows so graph ingestion does not depend on
    provider-specific prompt text or timestamp heuristics.
    """
    if not relationships:
        return dict(metadata)

    enriched = dict(metadata)
    for key, value in relationships.items():
        if key not in WORKFLOW_RELATIONSHIP_FIELDS or not _has_value(value):
            continue
        if key in {
            "plan_submitted_at",
            "questions_submitted_at",
            "feedback_submitted_at",
        }:
            enriched[key] = _append_unique(enriched.get(key), value)
        else:
            enriched[key] = value

    changespec_name = _non_empty(enriched.get("changespec_name")) or _non_empty(
        enriched.get("commit_changespec_name")
    )
    if changespec_name:
        enriched["changespec_name"] = changespec_name
        enriched.setdefault("cl_name", changespec_name)

    phase_bead_id = _non_empty(enriched.get("phase_bead_id"))
    if phase_bead_id:
        enriched.setdefault("bead_id", phase_bead_id)
    else:
        for key in ("epic_bead_id", "legend_bead_id"):
            bead_id = _non_empty(enriched.get(key))
            if bead_id:
                enriched.setdefault("bead_id", bead_id)
                break

    return enriched


def update_agent_artifact_metadata(
    artifacts_dir: str,
    relationships: dict[str, Any],
) -> dict[str, Any] | None:
    """Read, enrich, and rewrite ``agent_meta.json`` with relationship fields."""
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(metadata, dict):
        return None

    metadata = enrich_agent_workflow_relationships(metadata, relationships)
    enriched = enrich_agent_artifact_metadata(
        metadata,
        artifacts_dir=artifacts_dir,
        agent_name=_non_empty(metadata.get("name")),
        cl_name=_non_empty(metadata.get("changespec_name"))
        or _non_empty(metadata.get("cl_name"))
        or _non_empty(metadata.get("commit_changespec_name")),
        bead_id=_non_empty(metadata.get("bead_id")),
        parent_agent_timestamp=_non_empty(metadata.get("parent_agent_timestamp"))
        or _non_empty(metadata.get("parent_timestamp")),
        parent_agent_name=_non_empty(metadata.get("parent_agent_name")),
    )
    meta_path.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    return enriched


def workflow_relationships_from_env(agent_name: str | None) -> dict[str, Any]:
    """Return per-agent workflow relationship metadata from the launch env."""
    raw = os.environ.get(SASE_AGENT_WORKFLOW_LINKS_ENV)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}

    common = data.get("*")
    specific = data.get(agent_name or "") if agent_name else None
    relationships: dict[str, Any] = {}
    if isinstance(common, dict):
        relationships.update(common)
    if isinstance(specific, dict):
        relationships.update(specific)
    return relationships


def write_agent_artifact_metadata(
    artifacts_dir: str,
    metadata: dict[str, Any],
    *,
    agent_name: str | None = None,
    cl_name: str | None = None,
    bead_id: str | None = None,
    parent_agent_timestamp: str | None = None,
    parent_agent_name: str | None = None,
    relationships: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich and write ``agent_meta.json`` in one step."""
    metadata = enrich_agent_workflow_relationships(metadata, relationships)
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


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _append_unique(existing: object, value: object) -> list[Any]:
    if isinstance(existing, list):
        values = list(existing)
    elif _has_value(existing):
        values = [existing]
    else:
        values = []

    incoming = list(value) if isinstance(value, list) else [value]
    for item in incoming:
        if _has_value(item) and item not in values:
            values.append(item)
    return values
