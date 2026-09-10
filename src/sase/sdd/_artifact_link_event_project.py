"""Local bead and aggregate projections for published artifact-link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import (
    ArtifactLinkEventObject as _ArtifactLinkEventObject,
    edge_from_row as _edge_from_row,
    event_remove_row as _event_remove_row,
    probe_row_from_edge as _probe_row_from_edge,
    reduce_events as _reduce_events,
    row_uses as _row_uses,
    rows_from_events,
)
from sase.sdd._artifact_link_event_local_store import artifact_link_local_event_root
from sase.sdd._artifact_link_store_support import validate_artifact_link_row
from sase.sdd.artifact_link_store import ArtifactLinkStore


@dataclass(frozen=True, slots=True)
class ArtifactLinkBeadProjectionResult:
    """Durability receipt for bead endpoint projection."""

    changed: bool
    receipt: bool
    diagnostic: str | None = None


def active_operation_ids_for_row(
    store: ArtifactLinkStore,
    row: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return active event-version operation ids for *row*'s canonical edge."""

    edge = _edge_from_row(validate_artifact_link_row(row))
    return _active_operation_ids_for_edge(store, edge)


def _active_operation_ids_for_edge(
    store: ArtifactLinkStore,
    edge: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return active event-version operation ids for a canonical event edge."""

    events = tuple(event.event for event in _iter_event_objects(store))
    if not events:
        return ()
    reduction = _reduce_events(events)
    reduced_edges = reduction.get("edges")
    if not isinstance(reduced_edges, list):
        return ()
    canonical_edge = _edge_from_row(_probe_row_from_edge(edge))
    for reduced in reduced_edges:
        if not isinstance(reduced, dict):
            continue
        if reduced.get("edge") != canonical_edge:
            continue
        versions = reduced.get("versions")
        if not isinstance(versions, list):
            return ()
        return tuple(
            str(version.get("operation_id") or "")
            for version in versions
            if isinstance(version, dict) and bool(version.get("active"))
        )
    return ()


def apply_events_to_beads(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
) -> ArtifactLinkBeadProjectionResult:
    if not objects:
        return ArtifactLinkBeadProjectionResult(changed=False, receipt=True)
    if store.beads_dir is None:
        return ArtifactLinkBeadProjectionResult(
            changed=False,
            receipt=False,
            diagnostic="artifact-link bead store is unavailable",
        )
    from sase.sdd.artifact_link_beads import (
        add_bead_endpoint_link,
        remove_bead_endpoint_link,
    )
    from sase.sdd._artifact_link_commit import (
        ArtifactLinkPersistError,
        commit_bead_link_events,
    )

    try:
        changed = False
        for item in objects:
            event = item.event
            operation_id = str(event["operation_id"])
            event_kind = event.get("kind")
            if not isinstance(event_kind, dict):
                continue
            event_type = str(event_kind.get("type") or "")
            if event_type == "edge-remove":
                row = _event_remove_row(event)
                if row is None:
                    continue
                for issue_id, target_ref, direction in _bead_endpoint_writes(row):
                    outcome = remove_bead_endpoint_link(
                        store.beads_dir,
                        issue_id=issue_id,
                        target_ref=target_ref,
                        relation=str(row.get("relation") or ""),
                        direction=direction,
                        now=str(event.get("created_at") or "") or None,
                        operation_id=operation_id,
                    )
                    changed = changed or bool(outcome.get("changed"))
                continue
            for row in _event_rows_for_beads(event):
                for issue_id, target_ref, direction in _bead_endpoint_writes(row):
                    outcome = add_bead_endpoint_link(
                        store.beads_dir,
                        issue_id=issue_id,
                        target_ref=target_ref,
                        relation=str(row.get("relation") or ""),
                        description=str(row.get("description") or ""),
                        origin=str(row.get("origin") or ""),
                        direction=direction,
                        uses=_row_uses(row),
                        now=str(row.get("created_at") or "") or None,
                        operation_id=operation_id,
                    )
                    changed = changed or bool(outcome.get("changed"))

        if changed or _bead_store_has_uncommitted_changes(store.beads_dir):
            commit_bead_link_events(
                store,
                artifacts_dir=artifacts_dir,
                mutation_origin=mutation_origin,
            )
        if _bead_store_has_uncommitted_changes(store.beads_dir):
            return ArtifactLinkBeadProjectionResult(
                changed=changed,
                receipt=False,
                diagnostic="artifact-link bead projection has uncommitted changes",
            )
        return ArtifactLinkBeadProjectionResult(changed=changed, receipt=True)
    except ArtifactLinkPersistError as exc:
        return ArtifactLinkBeadProjectionResult(
            changed=changed,
            receipt=False,
            diagnostic=exc.diagnostic,
        )
    except Exception as exc:  # noqa: BLE001 - outbox replay must retry cleanly.
        return ArtifactLinkBeadProjectionResult(
            changed=changed,
            receipt=False,
            diagnostic=str(exc),
        )


def _event_rows_for_beads(event: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    kind = event.get("kind")
    if isinstance(kind, dict) and str(kind.get("type") or "") == "baseline-import":
        rows = kind.get("rows")
        if isinstance(rows, list):
            return tuple(
                validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
            )
    return rows_from_events((event,))


def _bead_endpoint_writes(
    row: Mapping[str, Any],
) -> tuple[tuple[str, str, str], ...]:
    from sase.sdd.artifact_link_beads import bead_id_from_ref

    source_ref = str(row.get("source_ref") or "")
    target_ref = str(row.get("target_ref") or "")
    writes: list[tuple[str, str, str]] = []
    source_issue_id = bead_id_from_ref(source_ref)
    if source_issue_id is not None:
        writes.append((source_issue_id, target_ref, "out"))
    target_issue_id = bead_id_from_ref(target_ref)
    if target_issue_id is not None and target_issue_id != source_issue_id:
        writes.append((target_issue_id, source_ref, "in"))
    return tuple(writes)


def _bead_store_has_uncommitted_changes(beads_dir: Path) -> bool:
    git_root = _git_root_for(beads_dir)
    if git_root is None:
        return False
    try:
        scope = os.path.relpath(beads_dir, git_root)
    except ValueError:
        scope = "."
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            scope,
        ],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def _git_root_for(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def apply_events_to_aggregate(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
) -> tuple[dict[str, Any], ...]:
    if not objects:
        return ()
    if all(_event_type(item.event) == "baseline-import" for item in objects):
        return ()
    aggregate = store.rebuild_aggregate(
        exclude_pending_event_ids=(str(item.event["operation_id"]) for item in objects),
    )
    return tuple(
        dict(row) for row in aggregate.get("rows", ()) if isinstance(row, dict)
    )


def _event_type(event: Mapping[str, Any]) -> str:
    kind = event.get("kind")
    if not isinstance(kind, dict):
        return ""
    return str(kind.get("type") or "")


def _iter_event_objects(store: ArtifactLinkStore) -> Iterable[_ArtifactLinkEventObject]:
    seen_roots: set[Path] = set()
    roots = (
        *store.sidecar_roots.values(),
        artifact_link_local_event_root(store.project_key),
    )
    for root in roots:
        resolved = root.expanduser().resolve(strict=False)
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        events_root = resolved / "link-events" / "v1"
        if not events_root.is_dir():
            continue
        for path in sorted(events_root.rglob("*.json")):
            try:
                payload = path.read_bytes()
                relative = path.relative_to(resolved).as_posix()
                validated = dict(
                    require_rust_binding("artifact_link_event_validate_bytes")(
                        payload,
                        relative,
                    )
                )
            except Exception:
                continue
            yield _ArtifactLinkEventObject(
                event=dict(validated["event"]),
                canonical_json=str(validated["canonical_json"]),
                payload=payload,
                digest=str(validated["digest"]),
                relative_path=Path(str(validated["path"])),
            )


__all__ = [
    "ArtifactLinkBeadProjectionResult",
    "active_operation_ids_for_row",
    "apply_events_to_aggregate",
    "apply_events_to_beads",
]
