"""Thin Python adapter around the sase-core artifact-link collision partition."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_history import (
    ArtifactLinkCollisionEvidence,
    attach_collision_history,
    collided_digests_for,
)
from sase.sdd._artifact_link_event_quarantine import (
    ArtifactLinkQuarantineFinding,
    attach_admission_evidence,
)


@dataclass(frozen=True, slots=True)
class ArtifactLinkEventCandidate:
    """One durable, pending, or incoming payload plus locator metadata."""

    event: dict[str, Any]
    digest: str
    canonical_json: str
    tier: str
    source_locator: str | None = None
    root: str | None = None
    relative_path: str | None = None
    evidence: ArtifactLinkCollisionEvidence = field(
        default_factory=ArtifactLinkCollisionEvidence
    )


@dataclass(frozen=True, slots=True)
class ArtifactLinkCollisionPartition:
    """Accepted payloads plus typed quarantine findings."""

    accepted: tuple[ArtifactLinkEventCandidate, ...]
    findings: tuple[ArtifactLinkQuarantineFinding, ...]


def candidates_from_events(
    events: Iterable[Mapping[str, Any]],
    *,
    tier: str,
    source_locator: str | None = None,
) -> tuple[ArtifactLinkEventCandidate, ...]:
    """Build partition candidates from already-canonical event dicts."""

    return tuple(
        candidate_from_event(event, tier=tier, source_locator=source_locator)
        for event in events
    )


def candidate_from_event(
    event: Mapping[str, Any],
    *,
    tier: str,
    source_locator: str | None = None,
    root: str | None = None,
    relative_path: str | None = None,
    digest: str | None = None,
    canonical_json: str | None = None,
    evidence: ArtifactLinkCollisionEvidence | None = None,
) -> ArtifactLinkEventCandidate:
    """Return one candidate, computing digest/canonical JSON when omitted."""

    canonical = dict(
        require_rust_binding("artifact_link_event_canonicalize")(dict(event))
    )
    json_text = canonical_json or str(
        require_rust_binding("artifact_link_event_canonical_json")(canonical)
    )
    event_digest = digest or str(
        require_rust_binding("artifact_link_event_digest")(canonical)
    )
    return ArtifactLinkEventCandidate(
        event=canonical,
        digest=event_digest,
        canonical_json=json_text,
        tier=tier,
        source_locator=source_locator,
        root=root,
        relative_path=relative_path,
        evidence=evidence or ArtifactLinkCollisionEvidence(),
    )


def partition_artifact_link_candidates(
    candidates: Sequence[ArtifactLinkEventCandidate],
) -> ArtifactLinkCollisionPartition:
    """Select accepted payloads through sase-core after attaching evidence."""

    if not candidates:
        return ArtifactLinkCollisionPartition(accepted=(), findings=())
    with_admission = attach_admission_evidence(candidates)
    collided = collided_digests_for(with_admission)
    prepared = attach_collision_history(with_admission, collided_digests=collided)
    request = {
        "schema_version": int(
            require_rust_binding("artifact_link_collision_wire_schema_version")()
        ),
        "candidates": [_candidate_wire(candidate) for candidate in prepared],
    }
    result = require_rust_binding("artifact_link_collision_partition")(request)
    if not isinstance(result, Mapping):
        raise RuntimeError("sase_core_rs returned malformed collision partition")
    by_digest = _candidates_by_digest(prepared)
    accepted: list[ArtifactLinkEventCandidate] = []
    for item in result.get("accepted") or ():
        if not isinstance(item, Mapping):
            continue
        accepted.append(_accepted_candidate(item, by_digest))
    findings: list[ArtifactLinkQuarantineFinding] = []
    for group in result.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        findings.extend(_group_findings(group, by_digest))
    return ArtifactLinkCollisionPartition(
        accepted=tuple(accepted),
        findings=tuple(findings),
    )


def event_edge_identity(event: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Return the canonical edge identity for one event, if it carries an edge."""

    kind = event.get("kind")
    if not isinstance(kind, Mapping):
        return None
    edge = kind.get("edge")
    if not isinstance(edge, Mapping):
        return None
    edge_kind = str(edge.get("kind") or "")
    relation = str(edge.get("relation") or "")
    if edge_kind == "directed":
        return (
            "directed",
            str(edge.get("source_ref") or ""),
            relation,
            str(edge.get("target_ref") or ""),
        )
    if edge_kind == "undirected":
        left, right = sorted(
            (str(edge.get("left_ref") or ""), str(edge.get("right_ref") or ""))
        )
        return ("undirected", relation, left, right)
    return None


def _candidate_wire(candidate: ArtifactLinkEventCandidate) -> dict[str, object]:
    evidence = candidate.evidence
    if not isinstance(evidence, ArtifactLinkCollisionEvidence):
        evidence = ArtifactLinkCollisionEvidence()
    wire: dict[str, object] = {
        "event": dict(candidate.event),
        "digest": candidate.digest,
        "canonical_json": candidate.canonical_json,
        "tier": candidate.tier,
        "evidence": evidence.to_wire(),
    }
    if candidate.source_locator is not None:
        wire["source_locator"] = candidate.source_locator
    return wire


def _candidates_by_digest(
    candidates: Sequence[object],
) -> dict[str, list[ArtifactLinkEventCandidate]]:
    by_digest: dict[str, list[ArtifactLinkEventCandidate]] = {}
    for candidate in candidates:
        if not isinstance(candidate, ArtifactLinkEventCandidate):
            continue
        by_digest.setdefault(candidate.digest, []).append(candidate)
    return by_digest


def _accepted_candidate(
    item: Mapping[str, Any],
    by_digest: Mapping[str, Sequence[ArtifactLinkEventCandidate]],
) -> ArtifactLinkEventCandidate:
    digest = str(item.get("digest") or "")
    event = item.get("event")
    tier = str(item.get("tier") or "durable")
    locator = item.get("source_locator")
    matches = list(by_digest.get(digest, ()))
    original = next((match for match in matches if match.tier == tier), None)
    if original is None and matches:
        original = matches[0]
    if original is not None:
        return replace(
            original,
            event=dict(event) if isinstance(event, Mapping) else original.event,
            tier=tier,
            source_locator=(
                str(locator) if locator is not None else original.source_locator
            ),
        )
    return candidate_from_event(
        event if isinstance(event, Mapping) else {},
        tier=tier,
        source_locator=str(locator) if locator is not None else None,
        digest=digest,
    )


def _group_findings(
    group: Mapping[str, Any],
    by_digest: Mapping[str, Sequence[ArtifactLinkEventCandidate]],
) -> tuple[ArtifactLinkQuarantineFinding, ...]:
    rejected = group.get("rejected")
    if not isinstance(rejected, list) or not rejected:
        return ()
    accepted = group.get("accepted")
    accepted_digest = (
        str(accepted.get("digest") or "") if isinstance(accepted, Mapping) else ""
    )
    findings: list[ArtifactLinkQuarantineFinding] = []
    for item in rejected:
        if not isinstance(item, Mapping):
            continue
        digest = str(item.get("digest") or "")
        event = item.get("event")
        locator = item.get("source_locator")
        original = next(iter(by_digest.get(digest, ())), None)
        rejected_path = None if original is None else original.relative_path
        findings.append(
            ArtifactLinkQuarantineFinding(
                project_key=str(group.get("project_key") or ""),
                operation_id=str(group.get("operation_id") or ""),
                accepted_digest=accepted_digest,
                rejected_digest=digest,
                rejected_event=dict(event) if isinstance(event, Mapping) else {},
                basis=str(item.get("basis") or group.get("basis") or ""),
                detail=str(item.get("detail") or group.get("detail") or ""),
                source_locator=(
                    str(locator)
                    if locator is not None
                    else (None if original is None else original.source_locator)
                ),
                ambiguity=tuple(
                    str(note) for note in item.get("ambiguity") or () if str(note)
                ),
                rejected_path=rejected_path,
            )
        )
    return tuple(findings)


__all__ = [
    "ArtifactLinkCollisionPartition",
    "ArtifactLinkEventCandidate",
    "candidate_from_event",
    "candidates_from_events",
    "event_edge_identity",
    "partition_artifact_link_candidates",
]
