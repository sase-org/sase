"""Rewrites existing Links tables in Markdown documents from durable rows."""

from __future__ import annotations

from typing import Any

from sase.artifact_cli._link_health_constants import (
    LINKS_END,
    LINKS_START,
    REFERENCED_BY_END,
    REFERENCED_BY_START,
)
from sase.artifact_cli._link_health_tables import markdown_path_for
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_projection import safety_body
from sase.sdd.artifact_link_store import ArtifactLinkStore


def rebuild_existing_projections(
    store: ArtifactLinkStore, rows: list[dict[str, Any]]
) -> None:
    """Rewrite existing Links tables from truth. Never parse Markdown for state."""

    by_ref: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if ref:
                by_ref.setdefault(ref, []).append(row)
    upsert = require_rust_binding("links_block_upsert")
    label = require_rust_binding("artifact_relation_label")
    for artifact_ref, touching in by_ref.items():
        path = markdown_path_for(store, artifact_ref)
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if LINKS_START not in text:
            continue
        table_rows = []
        for row in touching:
            origin = str(row.get("origin") or "")
            if origin not in {"manual", "migrated", "derived"}:
                continue
            source = str(row.get("source_ref") or "")
            target = str(row.get("target_ref") or "")
            this_is_source = source == artifact_ref
            peer = target if this_is_source else source
            relation = str(row.get("relation") or "")
            try:
                shown = str(label(relation, this_is_source))
            except (TypeError, ValueError):
                shown = relation
            table_rows.append(
                {
                    "values": {
                        "relation": shown,
                        "artifact": peer,
                        "why": str(row.get("description") or ""),
                    },
                    "link_targets": {},
                }
            )
        table = {
            "schema_version": 1,
            "columns": [
                {"key": "relation", "label": "Relation", "numeric": False},
                {"key": "artifact", "label": "Artifact", "numeric": False},
                {"key": "why", "label": "Why", "numeric": False},
            ],
            "rows": table_rows,
            "omitted": 0,
        }
        try:
            updated = str(upsert(text, table))
        except (TypeError, ValueError):
            continue
        if _has_unmatched_managed_marker(text):
            continue
        if safety_body(updated) != safety_body(text):
            continue
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def _has_unmatched_managed_marker(text: str) -> bool:
    return text.count(LINKS_START) != text.count(LINKS_END) or text.count(
        REFERENCED_BY_START
    ) != text.count(REFERENCED_BY_END)


__all__ = [
    "rebuild_existing_projections",
]
