"""Link-graph health for ``sase artifact doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_cli.references import resolve_cli_reference
from sase.artifact_read_log import read_artifact_read_events
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_renames import repair_historical_artifact_renames
from sase.sdd._artifact_link_projection import safety_body
from sase.sdd._artifact_link_store_support import (
    kind_of_ref,
    read_artifact_link_index,
)
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    resolve_artifact_link_store,
)
from sase.sdd.artifact_link_outbox import inspect_artifact_link_outbox
from sase.sdd.referenced_by_doctor import missing_referenced_by_indexes
from sase.sdd.referenced_by_index import (
    REFERENCED_BY_LINKS_DIR,
    document_has_referenced_by_block,
)


_LINKS_START = "<!-- sase:links:start -->"
_LINKS_END = "<!-- sase:links:end -->"
_REFERENCED_BY_START = "<!-- sase:referenced-by:start -->"
_REFERENCED_BY_END = "<!-- sase:referenced-by:end -->"
_RESOLVED = frozenset({"exact", "drifted", "vcs_backed"})


@dataclass(frozen=True)
class ArtifactLinkHealthReport:
    """Doctor findings for the artifact link graph."""

    skipped: bool
    dangling: tuple[str, ...] = ()
    unpublished_agent_refs: tuple[str, ...] = ()
    stale_tables: tuple[str, ...] = ()
    missing_companions: tuple[str, ...] = ()
    orphaned_companions: tuple[str, ...] = ()
    missing_head_indexes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    read_events: int = 0
    recorded_read_events: int = 0
    durable_read_rows: int = 0
    durable_sidecar_rows: int = 0
    aggregate_rows: int = 0
    outbox_entries: int = 0
    outbox_dropped: int = 0
    rebuilt: bool = False
    repaired_renames: int = 0

    @property
    def healthy(self) -> bool:
        if self.skipped:
            return True
        return not any(
            (
                self.dangling,
                self.stale_tables,
                self.missing_companions,
                self.orphaned_companions,
                self.missing_head_indexes,
                self.errors,
            )
        )


def inspect_artifact_link_health(*, fix: bool = False) -> ArtifactLinkHealthReport:
    """Inspect (and optionally rebuild) the current project's link graph."""

    try:
        store = resolve_artifact_link_store()
    except Exception as exc:  # noqa: BLE001 - report the file index too
        return ArtifactLinkHealthReport(skipped=False, errors=(str(exc),))

    try:
        if fix:
            store.reconcile_aggregate()
        rows = [dict(row) for row in store.load_aggregate().get("rows", [])]
        sidecar_rows = store.durable_sidecar_rows()
    except Exception as exc:  # noqa: BLE001 - surface unsupported v1/schema errors
        return ArtifactLinkHealthReport(skipped=False, errors=(str(exc),))
    dangling, unpublished_agents = _dangling_refs(rows, store)
    orphaned_companions = _orphaned_link_indexes(store)
    repaired_renames = 0
    if fix:
        repair = repair_historical_artifact_renames(
            store,
            (*dangling, *orphaned_companions),
        )
        repaired_renames = len(repair.renames) if repair.changed else 0
        if repair.changed:
            try:
                rows = [dict(row) for row in store.load_aggregate().get("rows", [])]
                sidecar_rows = store.durable_sidecar_rows()
                dangling, unpublished_agents = _dangling_refs(rows, store)
                orphaned_companions = _orphaned_link_indexes(store)
            except Exception as exc:  # noqa: BLE001 - report the failed repair.
                return ArtifactLinkHealthReport(skipped=False, errors=(str(exc),))
    stale = _stale_tables(store, rows)
    missing_companions = _missing_companions(rows)
    missing_head = _missing_head_indexes(store)
    read_events = 0
    recorded_read_events = 0
    try:
        events = read_artifact_read_events(project=store.project_key)
        read_events = len(events)
        recorded_read_events = sum(1 for event in events if event.recorded_link)
    except Exception:  # noqa: BLE001 - missing log is not a doctor failure
        read_events = 0
        recorded_read_events = 0
    try:
        outbox = inspect_artifact_link_outbox(store.project_key)
    except Exception:  # noqa: BLE001 - outbox diagnostics should not fail doctor
        outbox = None

    if fix:
        _rebuild_existing_projections(store, rows)

    return ArtifactLinkHealthReport(
        skipped=False,
        dangling=tuple(dangling),
        unpublished_agent_refs=tuple(unpublished_agents),
        stale_tables=tuple(stale),
        missing_companions=tuple(missing_companions),
        orphaned_companions=tuple(orphaned_companions),
        missing_head_indexes=tuple(missing_head),
        read_events=read_events,
        recorded_read_events=recorded_read_events,
        durable_read_rows=_read_row_count((*sidecar_rows, *rows)),
        durable_sidecar_rows=len(sidecar_rows),
        aggregate_rows=len(rows),
        outbox_entries=0 if outbox is None else outbox.queued,
        outbox_dropped=0 if outbox is None else outbox.dropped,
        rebuilt=fix,
        repaired_renames=repaired_renames,
    )


def dangling_and_orphaned_artifact_link_refs(
    store: ArtifactLinkStore,
) -> tuple[str, ...]:
    """Return the exact candidate refs ``sase artifact doctor --fix`` repairs.

    A housekeeping sweep that wants the rename-repair job without the rest of
    ``inspect_artifact_link_health``'s fix pass (which also rewrites Markdown
    ``## Links`` tables in place with no commit of its own) calls this and
    :func:`sase.sdd._artifact_link_renames.repair_historical_artifact_renames`
    directly instead.
    """

    rows = [dict(row) for row in store.load_aggregate().get("rows", [])]
    dangling, _unpublished_agents = _dangling_refs(rows, store)
    orphaned_companions = _orphaned_link_indexes(store)
    return (*dangling, *orphaned_companions)


def _read_row_count(rows: tuple[dict[str, Any], ...]) -> int:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if str(row.get("relation") or "") != "read":
            continue
        seen.add(
            (
                str(row.get("source_ref") or ""),
                "read",
                str(row.get("target_ref") or ""),
            )
        )
    return len(seen)


def _dangling_refs(
    rows: list[dict[str, Any]],
    store: ArtifactLinkStore,
) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    dangling: list[str] = []
    unpublished_agents: list[str] = []
    bead_ids = _known_bead_ids(store)
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if not ref or ref in seen:
                continue
            seen.add(ref)
            if ref.startswith("bead:") and bead_ids is not None:
                if ref.removeprefix("bead:") not in bead_ids:
                    dangling.append(ref)
                continue
            try:
                result = resolve_cli_reference(ref)
            except (RuntimeError, ValueError):
                if kind_of_ref(ref) == "agent":
                    unpublished_agents.append(ref)
                else:
                    dangling.append(ref)
                continue
            if result.resolution.status not in _RESOLVED:
                if kind_of_ref(ref) == "agent":
                    unpublished_agents.append(ref)
                else:
                    dangling.append(ref)
    return sorted(dangling), sorted(unpublished_agents)


def _known_bead_ids(store: ArtifactLinkStore) -> set[str] | None:
    if store.beads_dir is None:
        return None
    try:
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        with open_bead_project_for_beads_dir(store.beads_dir) as project:
            return {str(issue.id) for issue in project.list_issues()}
    except Exception:  # noqa: BLE001 - fall back to regular artifact resolution
        return None


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


def _orphaned_link_indexes(store: ArtifactLinkStore) -> list[str]:
    orphaned: list[str] = []
    seen: set[str] = set()
    for kind, root in store.sidecar_roots.items():
        links_root = root / REFERENCED_BY_LINKS_DIR
        if not links_root.is_dir():
            continue
        for path in sorted(links_root.rglob("*.json")):
            relative = path.relative_to(links_root).as_posix()
            if not relative.endswith(".json"):
                continue
            fallback_ref = f"{kind}:{relative[: -len('.json')]}"
            try:
                index = read_artifact_link_index(path, artifact_ref=fallback_ref)
            except Exception:  # noqa: BLE001 - malformed indexes are separate health.
                continue
            ref = str(index.get("artifact_ref") or fallback_ref)
            if ref in seen:
                continue
            seen.add(ref)
            artifact_path = _artifact_path_for(root, ref)
            if artifact_path is not None and not artifact_path.is_file():
                orphaned.append(ref)
    return sorted(orphaned)


def _artifact_path_for(root: Path, artifact_ref: str) -> Path | None:
    try:
        _kind, separator, relpath = artifact_ref.partition(":")
        if not separator or not relpath:
            return None
        relative = Path(relpath)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            return None
    except (TypeError, ValueError):
        return None
    return root / relative


def _missing_head_indexes(store: ArtifactLinkStore) -> list[str]:
    missing: list[str] = []
    for kind, root in store.sidecar_roots.items():
        if not root.is_dir():
            continue
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
    return text.count(_LINKS_START) != text.count(_LINKS_END) or text.count(
        _REFERENCED_BY_START
    ) != text.count(_REFERENCED_BY_END)


__all__ = [
    "ArtifactLinkHealthReport",
    "dangling_and_orphaned_artifact_link_refs",
    "inspect_artifact_link_health",
]
