"""Read durable and pending artifact-link events into one reduced snapshot."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
import time
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_collision import (
    ArtifactLinkEventCandidate,
    candidate_from_event,
    event_edge_identity,
    partition_artifact_link_candidates,
)
from sase.sdd._artifact_link_event_quarantine import (
    ArtifactLinkQuarantineFinding,
    load_artifact_link_quarantine_records,
    merge_quarantine_findings,
)
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
    durable_events: tuple[dict[str, Any], ...] = ()
    pending_events: tuple[dict[str, Any], ...] = ()
    accepted_events: tuple[dict[str, Any], ...] = ()
    candidates: tuple[ArtifactLinkEventCandidate, ...] = ()
    aliases: tuple[dict[str, str], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    validation_findings: tuple[ArtifactLinkEventValidationFinding, ...] = ()
    reduction_errors: tuple[str, ...] = ()
    orphaned_tombstones: tuple[str, ...] = ()
    quarantine_findings: tuple[ArtifactLinkQuarantineFinding, ...] = ()
    pending_stats: _ArtifactLinkPendingStats = _ArtifactLinkPendingStats()
    durable_event_count: int = 0
    pending_event_count: int = 0
    _edge_identity_cache: frozenset[tuple[str, ...]] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _alias_terminal_cache: dict[str, str] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _alias_terminal_error: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _alias_terminals_ready: bool = field(
        default=False, init=False, repr=False, compare=False
    )

    @property
    def has_inputs(self) -> bool:
        return self.durable_event_count > 0 or self.pending_event_count > 0

    @property
    def healthy(self) -> bool:
        return not self.blocking_problem_messages

    @property
    def blocking_problem_messages(self) -> tuple[str, ...]:
        return (
            *(finding.render() for finding in self.validation_findings),
            *self.reduction_errors,
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
            + _join_problems(self.blocking_problem_messages)
        )

    def _cached_edge_identities(self) -> frozenset[tuple[str, ...]]:
        cached = self._edge_identity_cache
        if cached is None:
            identities = set(_event_edge_identities(self.edges))
            for finding in self.quarantine_findings:
                identity = event_edge_identity(finding.rejected_event)
                if identity is not None:
                    identities.add(identity)
            cached = frozenset(identities)
            object.__setattr__(self, "_edge_identity_cache", cached)
        return cached

    def covers_row(self, row: Mapping[str, Any]) -> bool:
        """Return whether event truth has consulted this row's identity."""

        if not self.has_inputs or self.blocking_problem_messages:
            return False
        identities = self._cached_edge_identities()
        if artifact_link_row_identity(row) in identities:
            return True
        try:
            return self._resolved_row_identity(row) in identities
        except (TypeError, ValueError, RuntimeError):
            return False

    def _cached_alias_terminals(self) -> dict[str, str] | None:
        """Return the snapshot's alias terminal map from one cached sase-core call."""
        if self._alias_terminals_ready:
            if self._alias_terminal_error is not None:
                raise ValueError(self._alias_terminal_error)
            return self._alias_terminal_cache
        try:
            resolved = require_rust_binding("artifact_link_event_resolve_aliases")(
                list(self.aliases),
                [str(alias["old_ref"]) for alias in self.aliases],
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            message = str(exc)
            object.__setattr__(self, "_alias_terminal_error", message)
            object.__setattr__(self, "_alias_terminal_cache", None)
            object.__setattr__(self, "_alias_terminals_ready", True)
            raise ValueError(message) from exc
        resolved_refs = (
            resolved.get("resolved_refs") if isinstance(resolved, Mapping) else None
        )
        if not isinstance(resolved_refs, Mapping):
            object.__setattr__(self, "_alias_terminal_cache", None)
            object.__setattr__(self, "_alias_terminals_ready", True)
            return None
        terminal = {str(key): str(value) for key, value in resolved_refs.items()}
        object.__setattr__(self, "_alias_terminal_cache", terminal)
        object.__setattr__(self, "_alias_terminals_ready", True)
        return terminal

    def _resolved_row_identity(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        """Resolve a row through one cached sase-core alias call per snapshot."""
        if not self.aliases:
            return artifact_link_row_identity(row)
        validated = validate_artifact_link_row(row)
        source = canonicalize_artifact_link_ref(str(validated["source_ref"]))
        target = canonicalize_artifact_link_ref(str(validated["target_ref"]))
        terminal = self._cached_alias_terminals()
        if terminal is None:
            return artifact_link_row_identity(validated)
        resolved_row = dict(validated)
        resolved_row["source_ref"] = terminal.get(source, source)
        resolved_row["target_ref"] = terminal.get(target, target)
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

        durable_candidates, findings, roots = self._durable_candidates()
        pending_candidates, pending_stats = (
            self._pending_candidates(
                now=now,
                exclude_operation_ids=exclude_pending_event_ids,
            )
            if include_pending
            else ((), _ArtifactLinkPendingStats())
        )
        persisted, persisted_errors = load_artifact_link_quarantine_records(roots)
        quarantine_errors = tuple(
            ArtifactLinkEventValidationFinding(
                "invalid-quarantine",
                error.split(": ", 1)[0],
                error.split(": ", 1)[-1] if ": " in error else error,
            )
            for error in persisted_errors
        )
        return reduce_artifact_link_event_inputs(
            candidates=(*durable_candidates, *pending_candidates),
            validation_findings=(*findings, *quarantine_errors),
            pending_stats=pending_stats,
            persisted_quarantine=persisted,
            strict=strict,
        )

    def _durable_candidates(
        self,
    ) -> tuple[
        tuple[ArtifactLinkEventCandidate, ...],
        tuple[ArtifactLinkEventValidationFinding, ...],
        tuple[Path, ...],
    ]:
        candidates: list[ArtifactLinkEventCandidate] = []
        findings: list[ArtifactLinkEventValidationFinding] = []
        seen_roots: set[Path] = set()
        roots: list[Path] = []
        labeled_roots = (
            *self.sidecar_roots.items(),
            ("local", artifact_link_local_event_root(self.project_key)),
        )
        for kind, root in labeled_roots:
            root = root.expanduser().resolve(strict=False)
            if root in seen_roots:
                continue
            seen_roots.add(root)
            roots.append(root)
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
                    candidates.append(
                        candidate_from_event(
                            event,
                            tier="durable",
                            source_locator=f"{kind}:{relpath}",
                            root=str(root),
                            relative_path=relpath,
                            digest=str(validated["digest"]),
                            canonical_json=str(validated["canonical_json"]),
                        )
                    )
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
        return tuple(candidates), tuple(findings), tuple(roots)

    def _pending_candidates(
        self,
        *,
        now: float | None,
        exclude_operation_ids: Iterable[str],
    ) -> tuple[tuple[ArtifactLinkEventCandidate, ...], _ArtifactLinkPendingStats]:
        from sase.sdd.artifact_link_outbox import (
            pending_artifact_link_outbox_event_created_at,
            pending_artifact_link_outbox_events,
        )

        events = pending_artifact_link_outbox_events(
            self.project_key,
            exclude_operation_ids=exclude_operation_ids,
        )
        candidates = tuple(
            candidate_from_event(
                event,
                tier="pending",
                source_locator=f"pending:outbox:{event.get('operation_id') or ''}",
            )
            for event in events
        )
        return (
            candidates,
            _pending_stats(
                pending_artifact_link_outbox_event_created_at(
                    self.project_key,
                    exclude_operation_ids=exclude_operation_ids,
                ),
                now=now,
            ),
        )


def reduce_artifact_link_event_inputs(
    *,
    durable_events: Iterable[Mapping[str, Any]] = (),
    pending_events: Iterable[Mapping[str, Any]] = (),
    incoming_events: Iterable[Mapping[str, Any]] = (),
    candidates: Iterable[ArtifactLinkEventCandidate] | None = None,
    validation_findings: Iterable[ArtifactLinkEventValidationFinding] = (),
    pending_stats: _ArtifactLinkPendingStats | None = None,
    persisted_quarantine: Iterable[ArtifactLinkQuarantineFinding] = (),
    strict: bool = False,
) -> ArtifactLinkEventSnapshot:
    """Partition then reduce already-validated durable and pending event inputs."""

    prepared: list[ArtifactLinkEventCandidate] = (
        list(candidates)
        if candidates is not None
        else [
            *candidates_from_tier(durable_events, "durable"),
            *candidates_from_tier(pending_events, "pending"),
        ]
    )
    if incoming_events:
        prepared.extend(candidates_from_tier(incoming_events, "incoming"))
    prepared_candidates = tuple(prepared)
    durable = tuple(
        dict(candidate.event)
        for candidate in prepared_candidates
        if candidate.tier == "durable"
    )
    pending = tuple(
        dict(candidate.event)
        for candidate in prepared_candidates
        if candidate.tier == "pending"
    )
    rows: tuple[dict[str, Any], ...] = ()
    durable_rows: tuple[dict[str, Any], ...] = ()
    pending_rows: tuple[dict[str, Any], ...] = ()
    accepted_events: tuple[dict[str, Any], ...] = ()
    aliases: tuple[dict[str, str], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    reduction_errors: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    findings: tuple[ArtifactLinkQuarantineFinding, ...] = ()
    if prepared_candidates:
        try:
            partition = partition_artifact_link_candidates(prepared_candidates)
            findings = partition.findings
            accepted_events = tuple(dict(item.event) for item in partition.accepted)
            accepted_durable = tuple(
                dict(item.event)
                for item in partition.accepted
                if item.tier == "durable"
            )
            accepted_pending = tuple(
                dict(item.event)
                for item in partition.accepted
                if item.tier == "pending"
            )
            if accepted_durable:
                durable_rows = _reduced_rows(
                    require_rust_binding("artifact_link_events_reduce")(
                        list(accepted_durable),
                        [],
                    )
                )
            if accepted_pending:
                pending_rows = _reduced_rows(
                    require_rust_binding("artifact_link_events_reduce")(
                        [*_alias_events(accepted_durable), *accepted_pending],
                        [],
                    )
                )
            if accepted_events:
                reduction = require_rust_binding("artifact_link_events_reduce")(
                    list(accepted_events),
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
        durable_events=durable,
        pending_events=pending,
        accepted_events=accepted_events,
        candidates=prepared_candidates,
        aliases=aliases,
        edges=edges,
        validation_findings=tuple(validation_findings),
        reduction_errors=reduction_errors,
        orphaned_tombstones=orphaned,
        quarantine_findings=merge_quarantine_findings(
            findings,
            persisted_quarantine,
        ),
        pending_stats=pending_stats or _ArtifactLinkPendingStats(),
        durable_event_count=len(durable),
        pending_event_count=len(pending),
    )
    if strict:
        snapshot.assert_healthy()
    return snapshot


def candidates_from_tier(
    events: Iterable[Mapping[str, Any]],
    tier: str,
) -> tuple[ArtifactLinkEventCandidate, ...]:
    return tuple(candidate_from_event(event, tier=tier) for event in events)


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
    "ArtifactLinkEventCandidate",
    "ArtifactLinkEventSnapshot",
    "ArtifactLinkEventStoreAdapter",
    "ArtifactLinkEventValidationFinding",
    "ArtifactLinkQuarantineFinding",
    "reduce_artifact_link_event_inputs",
]
