"""Link-graph health for ``sase artifact doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_cli.references import resolve_cli_reference
from sase.artifact_read_log import read_artifact_read_events
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_migrate import migrate_links_tree
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    artifact_links_enabled,
    resolve_artifact_link_store,
)
from sase.sdd.referenced_by_doctor import missing_referenced_by_indexes
from sase.sdd.referenced_by_index import document_has_referenced_by_block


_LINKS_START = "<!-- sase:links:start -->"
_RESOLVED = frozenset({"exact", "drifted", "vcs_backed"})


@dataclass(frozen=True)
class ArtifactLinkHealthReport:
    """Doctor findings for the artifact link graph."""

    enabled: bool
    skipped: bool
    dangling: tuple[str, ...] = ()
    stale_tables: tuple[str, ...] = ()
    missing_companions: tuple[str, ...] = ()
    missing_head_indexes: tuple[str, ...] = ()
    migrated_paths: tuple[str, ...] = ()
    read_events: int = 0
    rebuilt: bool = False

    @property
    def healthy(self) -> bool:
        if self.skipped:
            return True
        return not any(
            (
                self.dangling,
                self.stale_tables,
                self.missing_companions,
                self.missing_head_indexes,
            )
        )


def inspect_artifact_link_health(*, fix: bool = False) -> ArtifactLinkHealthReport:
    """Inspect (and optionally rebuild) the current project's link graph."""

    if not artifact_links_enabled():
        return ArtifactLinkHealthReport(enabled=False, skipped=True)
    try:
        store = resolve_artifact_link_store()
    except Exception:  # noqa: BLE001 - doctor never breaks the index report
        return ArtifactLinkHealthReport(enabled=True, skipped=True)

    migrated: list[str] = []
    if fix:
        for root in store.sidecar_roots.values():
            for path in migrate_links_tree(root, write=True):
                migrated.append(str(path))
        store.rebuild_aggregate()

    rows = [dict(row) for row in store.load_aggregate().get("rows", [])]
    dangling = _dangling_refs(rows)
    stale = _stale_tables(store, rows)
    missing_companions = _missing_companions(rows)
    missing_head = _missing_head_indexes(store)
    read_events = 0
    try:
        read_events = len(read_artifact_read_events(project=store.project_key))
    except Exception:  # noqa: BLE001 - missing log is not a doctor failure
        read_events = 0

    if fix:
        _rebuild_existing_projections(store, rows)

    return ArtifactLinkHealthReport(
        enabled=True,
        skipped=False,
        dangling=tuple(dangling),
        stale_tables=tuple(stale),
        missing_companions=tuple(missing_companions),
        missing_head_indexes=tuple(missing_head),
        migrated_paths=tuple(migrated),
        read_events=read_events,
        rebuilt=fix,
    )


def _dangling_refs(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    dangling: list[str] = []
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if not ref or ref in seen:
                continue
            seen.add(ref)
            try:
                result = resolve_cli_reference(ref)
            except (RuntimeError, ValueError):
                dangling.append(ref)
                continue
            if result.resolution.status not in _RESOLVED:
                dangling.append(ref)
    return sorted(dangling)


def _stale_tables(store: ArtifactLinkStore, rows: list[dict[str, Any]]) -> list[str]:
    stale: list[str] = []
    by_ref: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if ref:
                by_ref.setdefault(ref, []).append(row)
    for artifact_ref, touching in by_ref.items():
        path = _markdown_path_for(store, artifact_ref)
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _LINKS_START not in text and not document_has_referenced_by_block(text):
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
        if origin not in {"manual", "migrated"}:
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


def _missing_companions(rows: list[dict[str, Any]]) -> list[str]:
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
                result = resolve_cli_reference(ref)
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


def _missing_head_indexes(store: ArtifactLinkStore) -> list[str]:
    missing: list[str] = []
    for kind, root in store.sidecar_roots.items():
        for relpath in missing_referenced_by_indexes(root):
            missing.append(f"{kind}:{relpath}")
    return sorted(missing)


def _markdown_path_for(store: ArtifactLinkStore, artifact_ref: str) -> Path | None:
    root = store.sidecar_root_for(artifact_ref)
    if root is None:
        return None
    _kind, _sep, relpath = artifact_ref.partition(":")
    if not relpath:
        return None
    path = (root / relpath).expanduser()
    return path if path.suffix == ".md" else None


def _rebuild_existing_projections(
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
        path = _markdown_path_for(store, artifact_ref)
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _LINKS_START not in text:
            continue
        table_rows = []
        for row in touching:
            origin = str(row.get("origin") or "")
            if origin not in {"manual", "migrated"}:
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
        if updated != text:
            path.write_text(updated, encoding="utf-8")


__all__ = ["ArtifactLinkHealthReport", "inspect_artifact_link_health"]
