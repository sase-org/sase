"""Convert v1 Referenced By ``links/*.json`` files into v2 link-graph rows."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd.referenced_by_index import (
    REFERENCED_BY_INDEX_SCHEMA_VERSION,
    REFERENCED_BY_LINKS_DIR,
    referenced_by_index_schema_version,
)

_MAX_DESCRIPTION_CHARS = 240
_V1_FALLBACK_CREATED_AT = "1970-01-01T00:00:00Z"


def migrate_v1_index_to_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one v1 Referenced By index document into a v2 link index.

    Each v1 citation becomes a ``cites`` row with ``origin: prompt_ref``. The
    description is synthesized from the recorded canonical ref and publish
    date; it is never the constant ``Cited in launch prompt``.
    """

    if payload.get("schema_version") != REFERENCED_BY_INDEX_SCHEMA_VERSION:
        raise RuntimeError(
            "v1 referenced-by migration requires schema_version "
            f"{REFERENCED_BY_INDEX_SCHEMA_VERSION}"
        )
    artifact_id = str(payload.get("artifact_id") or "").strip()
    if not artifact_id:
        raise RuntimeError("v1 referenced-by index missing artifact_id")
    canonicalize = require_rust_binding("artifact_link_canonicalize")
    validate_row = require_rust_binding("artifact_link_validate_row")
    target_ref = str(canonicalize(artifact_id))
    rows: list[dict[str, Any]] = []
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError("v1 referenced-by index rows must be a list")
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        migrated = _migrate_v1_row(raw, target_ref=target_ref)
        if migrated is None:
            continue
        rows.append(dict(validate_row(migrated)))
    return {
        "schema_version": 2,
        "artifact_ref": target_ref,
        "rows": rows,
    }


def migrate_links_tree(repo_root: Path, *, write: bool = False) -> tuple[Path, ...]:
    """Migrate v1 ``links/*.json`` files under *repo_root*.

    Dry-run by default. Returns the paths that would be (or were) rewritten.
    Schema-2 files are left untouched.
    """

    links_root = repo_root / REFERENCED_BY_LINKS_DIR
    if not links_root.is_dir():
        return ()
    changed: list[Path] = []
    for path in sorted(links_root.rglob("*.json")):
        if referenced_by_index_schema_version(path) != (
            REFERENCED_BY_INDEX_SCHEMA_VERSION
        ):
            continue
        payload = _read_json_object(path)
        migrated = migrate_v1_index_to_v2(payload)
        changed.append(path)
        if write:
            from sase.agents_sync.io import atomic_write_json

            atomic_write_json(path, migrated)
    return tuple(changed)


def _migrate_v1_row(
    raw: Mapping[str, Any], *, target_ref: str
) -> dict[str, Any] | None:
    agent = str(raw.get("agent") or "").strip()
    if not agent:
        return None
    canonical_ref = str(raw.get("canonical_ref") or "").strip()
    published = str(raw.get("published") or "").strip()
    uses = raw.get("uses")
    uses_n = uses if isinstance(uses, int) and not isinstance(uses, bool) else 1
    if uses_n <= 0:
        uses_n = 1
    return {
        "schema_version": 2,
        "source_ref": f"agent:{agent}",
        "relation": "cites",
        "target_ref": target_ref,
        "description": _v1_description(canonical_ref or target_ref, published),
        "origin": "prompt_ref",
        "created_by": agent,
        "created_at": _v1_created_at(published),
        "uses": uses_n,
    }


def _v1_description(canonical_ref: str, published: str) -> str:
    if canonical_ref and published:
        text = f"{canonical_ref} on {published}"
    elif canonical_ref:
        text = canonical_ref
    elif published:
        text = f"prompt citation on {published}"
    else:
        text = "prompt citation"
    if len(text) > _MAX_DESCRIPTION_CHARS:
        return text[:_MAX_DESCRIPTION_CHARS]
    return text


def _v1_created_at(published: str) -> str:
    text = published.strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        date = text[:10]
        if text.startswith(date) and "T" in text:
            return text if text.endswith("Z") or "+" in text[10:] else f"{text}Z"
        return f"{date}T00:00:00Z"
    if text:
        return text
    return _V1_FALLBACK_CREATED_AT


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"referenced-by index must be a JSON object: {path}")
    return payload


__all__ = [
    "migrate_links_tree",
    "migrate_v1_index_to_v2",
]
