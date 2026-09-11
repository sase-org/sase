"""Rendered ``## Links`` table and companion-file checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.artifact_cli._link_health_constants import LINKS_START
from sase.artifact_cli.references import resolve_cli_reference
from sase.artifact_refs import ArtifactRefContext
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.referenced_by_index import document_has_referenced_by_block


def stale_tables(store: ArtifactLinkStore, rows: list[dict[str, Any]]) -> list[str]:
    stale: list[str] = []
    by_ref: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if ref:
                by_ref.setdefault(ref, []).append(row)
    for artifact_ref, touching in by_ref.items():
        path = markdown_path_for(store, artifact_ref)
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if LINKS_START not in text and not document_has_referenced_by_block(text):
            continue
        parsed = dict(require_rust_binding("links_block_parse")(text))
        table = parsed.get("table")
        rendered_peers = _rendered_peer_keys(table if isinstance(table, dict) else None)
        expected = _curated_peer_keys(artifact_ref, touching)
        if rendered_peers != expected:
            stale.append(artifact_ref)
    return sorted(stale)


def _rendered_peer_keys(table: dict[str, Any] | None) -> set[tuple[str, str]]:
    if table is None:
        return set()
    keys: set[tuple[str, str]] = set()
    for raw in table.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        values = raw.get("values")
        if not isinstance(values, dict):
            continue
        relation = str(values.get("relation") or "")
        artifact = str(values.get("artifact") or "")
        if relation and artifact:
            keys.add((relation, artifact))
    return keys


def _curated_peer_keys(
    artifact_ref: str, rows: list[dict[str, Any]]
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    label = require_rust_binding("artifact_relation_label")
    for row in rows:
        origin = str(row.get("origin") or "")
        if origin not in {"manual", "migrated", "derived"}:
            continue
        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        relation = str(row.get("relation") or "")
        this_is_source = source == artifact_ref
        peer = target if this_is_source else source
        try:
            shown = str(label(relation, this_is_source))
        except (TypeError, ValueError):
            shown = relation
        keys.add((shown, peer))
    return keys


def missing_companions(
    rows: list[dict[str, Any]], *, context: ArtifactRefContext
) -> list[str]:
    missing: list[str] = []
    seen: set[str] = set()
    md_path = require_rust_binding("artifact_md_path")
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if not ref or ref in seen:
                continue
            seen.add(ref)
            try:
                result = resolve_cli_reference(ref, context=context)
            except (RuntimeError, ValueError):
                continue
            request = {
                "schema_version": 1,
                "reference": ref,
                "resolved_path": (
                    None
                    if result.resolution.resolved_path is None
                    else str(result.resolution.resolved_path)
                ),
            }
            try:
                payload = dict(md_path(request))
            except (TypeError, ValueError):
                continue
            if str(payload.get("kind") or "") != "companion":
                continue
            path = payload.get("path")
            if isinstance(path, str) and path and not Path(path).is_file():
                missing.append(ref)
    return sorted(missing)


def markdown_path_for(store: ArtifactLinkStore, artifact_ref: str) -> Path | None:
    root = store.sidecar_root_for(artifact_ref)
    if root is None:
        return None
    _kind, _sep, relpath = artifact_ref.partition(":")
    if not relpath:
        return None
    path = (root / relpath).expanduser()
    return path if path.suffix == ".md" else None


__all__ = [
    "markdown_path_for",
    "missing_companions",
    "stale_tables",
]
