"""Structured `.sase/referenced-by` index helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem

REFERENCED_BY_INDEX_SCHEMA_VERSION = 1


def referenced_by_index_path(repo_root: Path, artifact_id: str) -> Path:
    """Return the structured index path for *artifact_id* inside *repo_root*."""

    provider, separator, repo_relpath = artifact_id.partition(":")
    if not separator or not provider or not repo_relpath:
        raise ValueError(f"invalid referenced-by artifact id: {artifact_id!r}")
    rel = Path(repo_relpath)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"unsafe referenced-by artifact path: {repo_relpath!r}")
    return (
        repo_root
        / ".sase"
        / "referenced-by"
        / provider
        / rel.with_suffix(rel.suffix + ".json")
    )


def read_referenced_by_index(path: Path) -> dict[str, Any]:
    """Read one structured referenced-by index, or return an empty document."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": REFERENCED_BY_INDEX_SCHEMA_VERSION, "rows": []}
    if not isinstance(payload, dict):
        raise RuntimeError("referenced-by index must be a JSON object")
    if payload.get("schema_version") != REFERENCED_BY_INDEX_SCHEMA_VERSION:
        raise RuntimeError("unsupported referenced-by index schema")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("referenced-by index rows must be a list")
    return payload


def merge_referenced_by_rows(
    existing: dict[str, Any],
    requests: list[ReferencedByOutboxItem],
) -> dict[str, Any]:
    """Merge queued requests into an index document."""

    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in existing.get("rows", []):
        if not isinstance(raw, dict):
            continue
        agent = raw.get("agent")
        canonical_ref = raw.get("canonical_ref")
        if isinstance(agent, str) and isinstance(canonical_ref, str):
            rows_by_key[(agent, canonical_ref)] = dict(raw)
    for item in requests:
        rows_by_key[(item.global_agent, item.canonical_ref)] = {
            "agent": item.global_agent,
            "agent_url": item.agent_url,
            "project": item.project,
            "canonical_ref": item.canonical_ref,
            "destination": item.destination,
            "uses": item.uses,
            "published": item.published_date,
            "use_ids": [item.id],
        }
    first = requests[0] if requests else None
    artifact_id = (
        first.artifact_id
        if first is not None
        else str(existing.get("artifact_id") or "")
    )
    repo_relpath = (
        first.repo_relpath
        if first is not None
        else str(existing.get("repo_relpath") or "")
    )
    identity_value = (
        first.identity_value if first is not None else existing.get("identity_value")
    )
    return {
        "schema_version": REFERENCED_BY_INDEX_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "repo_relpath": repo_relpath,
        "identity_value": identity_value,
        "rows": sorted(
            rows_by_key.values(),
            key=lambda row: (
                str(row.get("agent") or ""),
                str(row.get("canonical_ref") or ""),
            ),
        ),
    }


__all__ = [
    "REFERENCED_BY_INDEX_SCHEMA_VERSION",
    "merge_referenced_by_rows",
    "read_referenced_by_index",
    "referenced_by_index_path",
]
