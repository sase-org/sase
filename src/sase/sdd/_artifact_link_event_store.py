"""Read durable and pending artifact-link events into one reduced snapshot."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import ceil
from pathlib import Path
import time
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import (
    artifact_link_row_identity,
    canonicalize_artifact_link_ref,
    validate_artifact_link_row,
)
from sase.sdd._artifact_link_event_local_store import artifact_link_local_event_root

ARTIFACT_LINK_EVENT_DIR = "link-events/v1"


@dataclass(frozen=True, slots=True)
class ArtifactLinkEventValidationFinding:
    """One invalid durable link-event object or path."""

    kind: str
    path: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True, slots=True)
class _ArtifactLinkPendingStats:
    """Age distribution for pending schema-v2 outbox event entries."""

    count: int = 0
    oldest_age_seconds: float = 0.0
    newest_age_seconds: float = 0.0
    p95_age_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ArtifactLinkEventSnapshot:
    """Rust-reduced artifact-link event state plus validation diagnostics."""

    rows: tuple[dict[str, Any], ...] = ()
    durable_rows: tuple[dict[str, Any], ...] = ()
    pending_rows: tuple[dict[str, Any], ...] = ()
    aliases: tuple[dict[str, str], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    validation_findings: tuple[ArtifactLinkEventValidationFinding, ...] = ()
    reduction_errors: tuple[str, ...] = ()
    orphaned_tombstones: tuple[str, ...] = ()
    pending_stats: _ArtifactLinkPendingStats = _ArtifactLinkPendingStats()
    durable_event_count: int = 0
    pending_event_count: int = 0

    @property
    def has_inputs(self) -> bool:
        return self.durable_event_count > 0 or self.pending_event_count > 0

    @property
    def healthy(self) -> bool:
        return not (
            self.validation_findings
            or self.reduction_errors
            or self.orphaned_tombstones
        )

    @property
    def problem_messages(self) -> tuple[str, ...]:
        return (
            *(finding.render() for finding in self.validation_findings),
            *self.reduction_errors,
            *self.orphaned_tombstones,
        )

    def assert_healthy(self) -> None:
        if self.healthy:
            return
        raise RuntimeError(
            "artifact-link event store is invalid: "
            + _join_problems(self.problem_messages)
        )

    def covers_row(self, row: Mapping[str, Any]) -> bool:
        """Return whether event truth has consulted this row's identity."""

        if not self.has_inputs or not self.healthy:
            return False
        identities = _event_edge_identities(self.edges)
        if artifact_link_row_identity(row) in identities:
            return True
        try:
            return self._resolved_row_identity(row) in identities
        except (TypeError, ValueError, RuntimeError):
            return False

    def _resolved_row_identity(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        if not self.aliases:
            return artifact_link_row_identity(row)
        validated = validate_artifact_link_row(row)
        source = canonicalize_artifact_link_ref(str(validated["source_ref"]))
        target = canonicalize_artifact_link_ref(str(validated["target_ref"]))
        resolved = require_rust_binding("artifact_link_event_resolve_aliases")(
            list(self.aliases),
            [source, target],
        )
        resolved_refs = resolved.get("resolved_refs")
        if not isinstance(resolved_refs, Mapping):
            return artifact_link_row_identity(validated)
        resolved_row = dict(validated)
        resolved_row["source_ref"] = str(resolved_refs.get(source, source))
        resolved_row["target_ref"] = str(resolved_refs.get(target, target))
        return artifact_link_row_identity(validate_artifact_link_row(resolved_row))


class ArtifactLinkEventStoreAdapter:
    """Filesystem adapter around the Rust artifact-link event reducer."""

    def __init__(self, project_key: str, sidecar_roots: Mapping[str, Path]) -> None:
        self.project_key = project_key
        self.sidecar_roots = {
            kind: root.expanduser().resolve(strict=False)
            for kind, root in sidecar_roots.items()
        }

    def snapshot(
        self,
        *,
        include_pending: bool = True,
        strict: bool = True,
        now: float | None = None,
        exclude_pending_event_ids: Iterable[str] = (),
    ) -> ArtifactLinkEventSnapshot:
        """Return reduced durable events, optionally overlaid with pending events."""

        durable_events, findings = self._durable_events()
        pending_events, pending_stats = (
            self._pending_events(
                now=now,
                exclude_operation_ids=exclude_pending_event_ids,
            )
            if include_pending
            else ((), _ArtifactLinkPendingStats())
        )
        reduction_events = (*durable_events, *pending_events)
        rows: tuple[dict[str, Any], ...] = ()
        durable_rows: tuple[dict[str, Any], ...] = ()
        pending_rows: tuple[dict[str, Any], ...] = ()
        aliases: tuple[dict[str, str], ...] = ()
        edges: tuple[dict[str, Any], ...] = ()
        reduction_errors: tuple[str, ...] = ()
        orphaned: tuple[str, ...] = ()
        if durable_events:
            try:
                durable_reduction = require_rust_binding("artifact_link_events_reduce")(
                    list(durable_events),
                    [],
                )
                durable_rows = _reduced_rows(durable_reduction)
            except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
                reduction_errors = (*reduction_errors, str(exc))
        if pending_events:
            try:
                pending_reduction = require_rust_binding("artifact_link_events_reduce")(
                    [*_alias_events(durable_events), *pending_events],
                    [],
                )
                pending_rows = _reduced_rows(pending_reduction)
            except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
                reduction_errors = (*reduction_errors, str(exc))
        if reduction_events:
            try:
                reduction = require_rust_binding("artifact_link_events_reduce")(
                    list(reduction_events),
                    [],
                )
                rows = _reduced_rows(reduction)
                aliases = _reduced_aliases(reduction)
                edges = _reduced_edges(reduction)
                orphaned = _orphaned_tombstones(edges)
            except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
                reduction_errors = (str(exc),)
        snapshot = ArtifactLinkEventSnapshot(
            rows=rows,
            durable_rows=durable_rows,
            pending_rows=pending_rows,
            aliases=aliases,
            edges=edges,
            validation_findings=findings,
            reduction_errors=reduction_errors,
            orphaned_tombstones=orphaned,
            pending_stats=pending_stats,
            durable_event_count=len(durable_events),
            pending_event_count=len(pending_events),
        )
        if strict:
            snapshot.assert_healthy()
        return snapshot

    def _durable_events(
        self,
    ) -> tuple[
        tuple[dict[str, Any], ...], tuple[ArtifactLinkEventValidationFinding, ...]
    ]:
        events: list[dict[str, Any]] = []
        findings: list[ArtifactLinkEventValidationFinding] = []
        seen_roots: set[Path] = set()
        roots = (
            *self.sidecar_roots.values(),
            artifact_link_local_event_root(self.project_key),
        )
        for root in roots:
            root = root.expanduser().resolve(strict=False)
            if root in seen_roots:
                continue
            seen_roots.add(root)
            for path in _iter_event_object_paths(root):
                try:
                    relpath = path.relative_to(root).as_posix()
                    validated = require_rust_binding(
                        "artifact_link_event_validate_bytes"
                    )(path.read_bytes(), relpath)
                    event = dict(validated["event"])
                    event_project = str(event.get("project_key") or "")
                    if event_project != self.project_key:
                        findings.append(
                            ArtifactLinkEventValidationFinding(
                                "project-mismatch",
                                relpath,
                                f"event project {event_project!r} != {self.project_key!r}",
                            )
                        )
                        continue
                    events.append(event)
                except (
                    OSError,
                    TypeError,
                    ValueError,
                    RuntimeError,
                    AttributeError,
                ) as exc:
                    findings.append(
                        ArtifactLinkEventValidationFinding(
                            "invalid-object",
                            _display_path(root, path),
                            str(exc),
                        )
                    )
        return tuple(events), tuple(findings)

    def _pending_events(
        self,
        *,
        now: float | None,
        exclude_operation_ids: Iterable[str],
    ) -> tuple[tuple[dict[str, Any], ...], _ArtifactLinkPendingStats]:
        from sase.sdd.artifact_link_outbox import (
            pending_artifact_link_outbox_event_created_at,
            pending_artifact_link_outbox_events,
        )

        return (
            pending_artifact_link_outbox_events(
                self.project_key,
                exclude_operation_ids=exclude_operation_ids,
            ),
            _pending_stats(
                pending_artifact_link_outbox_event_created_at(
                    self.project_key,
                    exclude_operation_ids=exclude_operation_ids,
                ),
                now=now,
            ),
        )


def _iter_event_object_paths(root: Path) -> Iterable[Path]:
    event_root = root / ARTIFACT_LINK_EVENT_DIR
    if not event_root.is_dir():
        return ()
    return sorted(
        path
        for path in event_root.rglob("*.json")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(event_root).parts)
    )


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _reduced_rows(reduction: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(reduction, Mapping):
        raise RuntimeError("sase_core_rs returned malformed link-event reduction")
    rows = reduction.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("sase_core_rs returned malformed link-event rows")
    return tuple(
        validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
    )


def _reduced_aliases(reduction: object) -> tuple[dict[str, str], ...]:
    if not isinstance(reduction, Mapping):
        return ()
    aliases = reduction.get("aliases")
    if not isinstance(aliases, list):
        return ()
    result: list[dict[str, str]] = []
    for item in aliases:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "old_ref": str(item.get("old_ref") or ""),
                "new_ref": str(item.get("new_ref") or ""),
            }
        )
    return tuple(result)


def _reduced_edges(reduction: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(reduction, Mapping):
        return ()
    edges = reduction.get("edges")
    if not isinstance(edges, list):
        return ()
    return tuple(dict(edge) for edge in edges if isinstance(edge, dict))


def _alias_events(events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("kind")
        if isinstance(kind, Mapping) and str(kind.get("type") or "") == "alias":
            result.append(dict(event))
    return tuple(result)


def _orphaned_tombstones(edges: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    messages: list[str] = []
    for edge_record in edges:
        tombstones = edge_record.get("tombstones")
        if not isinstance(tombstones, list) or not tombstones:
            continue
        versions = edge_record.get("versions")
        version_ids = (
            {
                str(version.get("operation_id") or "")
                for version in versions
                if isinstance(version, Mapping)
            }
            if isinstance(versions, list)
            else set()
        )
        for tombstone in tombstones:
            if not isinstance(tombstone, Mapping):
                continue
            observed = {
                str(operation_id)
                for operation_id in tombstone.get("observed_operation_ids") or ()
            }
            if observed and observed.intersection(version_ids):
                continue
            operation_id = str(tombstone.get("operation_id") or "<unknown>")
            messages.append(
                f"{_edge_text(edge_record.get('edge'))}: remove {operation_id} "
                "observes no known active version"
            )
    return tuple(messages)


def _event_edge_identities(
    edges: Iterable[Mapping[str, Any]],
) -> frozenset[tuple[str, ...]]:
    identities: set[tuple[str, ...]] = set()
    for edge_record in edges:
        edge = edge_record.get("edge")
        identity = _edge_identity(edge)
        if identity is not None:
            identities.add(identity)
    return frozenset(identities)


def _edge_identity(edge: object) -> tuple[str, ...] | None:
    if not isinstance(edge, Mapping):
        return None
    kind = str(edge.get("kind") or "")
    relation = str(edge.get("relation") or "")
    if kind == "directed":
        return (
            "directed",
            str(edge.get("source_ref") or ""),
            relation,
            str(edge.get("target_ref") or ""),
        )
    if kind == "undirected":
        left, right = sorted(
            (str(edge.get("left_ref") or ""), str(edge.get("right_ref") or ""))
        )
        return ("undirected", relation, left, right)
    return None


def _edge_text(edge: object) -> str:
    if not isinstance(edge, Mapping):
        return "<unknown edge>"
    kind = str(edge.get("kind") or "")
    relation = str(edge.get("relation") or "")
    if kind == "directed":
        return (
            f"{edge.get('source_ref') or ''} {relation} {edge.get('target_ref') or ''}"
        )
    if kind == "undirected":
        return f"{edge.get('left_ref') or ''} {relation} {edge.get('right_ref') or ''}"
    return "<unknown edge>"


def _pending_stats(
    created_at_values: Iterable[float],
    *,
    now: float | None,
) -> _ArtifactLinkPendingStats:
    observed_at = float(time.time() if now is None else now)
    ages = sorted(
        max(0.0, observed_at - float(created_at)) for created_at in created_at_values
    )
    if not ages:
        return _ArtifactLinkPendingStats()
    p95_index = min(len(ages) - 1, max(0, ceil(len(ages) * 0.95) - 1))
    return _ArtifactLinkPendingStats(
        count=len(ages),
        oldest_age_seconds=ages[-1],
        newest_age_seconds=ages[0],
        p95_age_seconds=ages[p95_index],
    )


def _join_problems(messages: Iterable[str]) -> str:
    problems = [message for message in messages if message]
    if len(problems) <= 4:
        return "; ".join(problems)
    return "; ".join((*problems[:4], f"... plus {len(problems) - 4} more"))


__all__ = [
    "ARTIFACT_LINK_EVENT_DIR",
    "ArtifactLinkEventSnapshot",
    "ArtifactLinkEventStoreAdapter",
    "ArtifactLinkEventValidationFinding",
]
