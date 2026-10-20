"""Classify artifact-link bead endpoints by owning store before projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from sase.bead.cross_project import (
    BeadStoreSnapshot,
    enabled_project_store_snapshots,
    probe_bead_target_owner,
    route_bead_target_via_probe,
)
from sase.core.bead_target_routing_facade import BeadTargetStoreDescriptor

if TYPE_CHECKING:
    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore

BeadEndpointKind = Literal["local", "foreign", "removed", "absent", "transient"]
BeadEndpointOutcome = Literal["committed", "removed", "absent", "foreign", "transient"]

_OUTCOME_RANK = {
    "committed": 0,
    "removed": 1,
    "absent": 1,
    "foreign": 1,
    "transient": 2,
}

_CLONE_LAG_DETAIL = "hidden bead clone is missing a local endpoint"


@dataclass(frozen=True, slots=True)
class _ClassifiedBeadEndpoint:
    """Owning-store classification for one bead id."""

    issue_id: str
    kind: BeadEndpointKind
    owner_project: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class BeadEndpointEvidence:
    """Per-operation publication evidence for one bead endpoint."""

    operation_id: str
    issue_id: str
    outcome: BeadEndpointOutcome
    owner_project: str | None = None
    detail: str | None = None

    @property
    def endpoint_ref(self) -> str:
        return f"bead:{self.issue_id}"

    def to_wire(self) -> dict[str, Any]:
        """Return the Rust ``bead_endpoints`` entry shape."""

        if self.outcome == "foreign":
            return {
                "endpoint_ref": self.endpoint_ref,
                "outcome": {
                    "foreign": {"owner_project": self.owner_project or "unknown"}
                },
            }
        if self.outcome == "transient":
            return {
                "endpoint_ref": self.endpoint_ref,
                "outcome": {"transient": {"detail": self.detail or "transient"}},
            }
        return {"endpoint_ref": self.endpoint_ref, "outcome": self.outcome}

    def as_transient(self, detail: str) -> BeadEndpointEvidence:
        return BeadEndpointEvidence(
            operation_id=self.operation_id,
            issue_id=self.issue_id,
            outcome="transient",
            detail=detail,
        )


def classify_bead_issue_ids(
    issue_ids: Iterable[str],
    store: ArtifactLinkStore,
) -> dict[str, _ClassifiedBeadEndpoint]:
    """Classify unique bead ids against this store and enabled-project snapshots."""

    unique = tuple(dict.fromkeys(issue_id for issue_id in issue_ids if issue_id))
    if not unique:
        return {}
    try:
        snapshots = enabled_project_store_snapshots()
    except Exception:
        snapshots = ()
    local = _local_store_descriptor_for(store)
    return {
        issue_id: _classify_bead_issue(
            issue_id,
            store=store,
            local=local,
            snapshots=snapshots,
        )
        for issue_id in unique
    }


def _classify_bead_issue(
    issue_id: str,
    *,
    store: ArtifactLinkStore,
    local: BeadTargetStoreDescriptor | None,
    snapshots: Sequence[BeadStoreSnapshot],
) -> _ClassifiedBeadEndpoint:
    """Route one bead id onto local, foreign, absent, removed, or transient."""

    if local is None or store.beads_dir is None:
        return _ClassifiedBeadEndpoint(
            issue_id,
            "transient",
            detail="artifact-link bead store is unavailable",
        )
    candidates = [
        snapshot.descriptor()
        for snapshot in snapshots
        if snapshot.store_key != local.store_key
    ]
    try:
        route = route_bead_target_via_probe(
            issue_id,
            local_store=local,
            candidates=candidates,
        )
    except Exception as exc:  # noqa: BLE001 - classification must not abort the batch.
        return _ClassifiedBeadEndpoint(issue_id, "transient", detail=str(exc))
    if route.error is not None:
        if route.error.kind == "not_found":
            return _ClassifiedBeadEndpoint(issue_id, "absent")
        return _ClassifiedBeadEndpoint(
            issue_id,
            "transient",
            detail=route.error.message or route.error.kind,
        )
    if route.store is not None and not _is_this_store(route.store, local):
        owner = (
            route.store.project_label
            or route.store.project_key
            or route.store.store_key
        )
        return _ClassifiedBeadEndpoint(
            issue_id,
            "foreign",
            owner_project=str(owner),
        )
    status, _stem = probe_bead_target_owner(store.beads_dir, issue_id)
    if status == "hit":
        return _ClassifiedBeadEndpoint(issue_id, "local")
    if status == "miss":
        canonical = _canonical_beads_dir(store, snapshots)
        projection_root = store.beads_dir.expanduser().resolve(strict=False)
        if canonical is not None and canonical != projection_root:
            canonical_status, _canonical_stem = probe_bead_target_owner(
                canonical, issue_id
            )
            if canonical_status == "hit":
                return _ClassifiedBeadEndpoint(
                    issue_id,
                    "transient",
                    detail=_CLONE_LAG_DETAIL,
                )
        return _ClassifiedBeadEndpoint(issue_id, "absent")
    return _ClassifiedBeadEndpoint(issue_id, "local")


def _local_store_descriptor_for(
    store: ArtifactLinkStore,
) -> BeadTargetStoreDescriptor | None:
    """Return the routing descriptor for this artifact-link store's bead root."""

    if store.beads_dir is None:
        return None
    beads_dir = store.beads_dir.expanduser().resolve(strict=False)
    unavailable_reason = None if beads_dir.is_dir() else "not readable"
    return BeadTargetStoreDescriptor(
        store_key=str(beads_dir),
        project_key=store.project_key,
        project_label=store.project_key,
        primary_workspace=None,
        beads_dir=beads_dir,
        issue_prefix=_stored_issue_prefix(beads_dir),
        project_refs=(store.project_key,),
        issue_ids=(),
        unavailable_reason=unavailable_reason,
    )


def partition_local_projection_requests(
    requests: Sequence[Mapping[str, Any]],
    classified: Mapping[str, _ClassifiedBeadEndpoint],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], BeadEndpointEvidence]]:
    """Keep local requests for skip-mode projection; evidence the rest now."""

    local_requests: list[dict[str, Any]] = []
    evidence: dict[tuple[str, str], BeadEndpointEvidence] = {}
    for request in requests:
        issue_id = str(request["issue_id"])
        operation_id = str(request["operation_id"])
        classification = classified.get(issue_id)
        if classification is None or classification.kind == "local":
            payload = dict(request)
            payload["missing_holder"] = "skip"
            local_requests.append(payload)
            continue
        keep_worse_evidence(
            evidence,
            BeadEndpointEvidence(
                operation_id=operation_id,
                issue_id=issue_id,
                outcome=classification.kind,
                owner_project=classification.owner_project,
                detail=classification.detail,
            ),
        )
    return local_requests, evidence


def evidence_from_projection_chunk(
    chunk: Sequence[Mapping[str, Any]],
    outcome: Mapping[str, Any] | None,
    *,
    transient_detail: str | None = None,
) -> dict[tuple[str, str], BeadEndpointEvidence]:
    """Map one skip-mode chunk onto per-operation endpoint evidence."""

    by_index: dict[int, Mapping[str, Any]] = {}
    raw_outcomes = None if outcome is None else outcome.get("link_projection_outcomes")
    if isinstance(raw_outcomes, list):
        for item in raw_outcomes:
            if not isinstance(item, Mapping):
                continue
            try:
                index = int(item["index"])
            except (KeyError, TypeError, ValueError):
                continue
            by_index[index] = item
    evidence: dict[tuple[str, str], BeadEndpointEvidence] = {}
    for index, request in enumerate(chunk):
        issue_id = str(request["issue_id"])
        operation_id = str(request["operation_id"])
        if transient_detail is not None:
            mapped: BeadEndpointOutcome = "transient"
            detail: str | None = transient_detail
        else:
            mapped, detail = _outcome_from_skip_item(by_index.get(index))
        keep_worse_evidence(
            evidence,
            BeadEndpointEvidence(
                operation_id=operation_id,
                issue_id=issue_id,
                outcome=mapped,
                detail=detail,
            ),
        )
    return evidence


def keep_worse_evidence(
    evidence: dict[tuple[str, str], BeadEndpointEvidence],
    item: BeadEndpointEvidence,
) -> None:
    """Keep the more blocking outcome when the same endpoint is classified twice."""

    key = (item.operation_id, item.issue_id)
    existing = evidence.get(key)
    if existing is None or _OUTCOME_RANK.get(item.outcome, 0) >= _OUTCOME_RANK.get(
        existing.outcome, 0
    ):
        evidence[key] = item


def demote_committed_evidence(
    evidence: Mapping[tuple[str, str], BeadEndpointEvidence],
    detail: str,
) -> dict[tuple[str, str], BeadEndpointEvidence]:
    """Turn committed outcomes into transients when the bead commit did not land."""

    return {
        key: (item.as_transient(detail) if item.outcome == "committed" else item)
        for key, item in evidence.items()
    }


def _outcome_from_skip_item(
    item: Mapping[str, Any] | None,
) -> tuple[BeadEndpointOutcome, str | None]:
    if item is None:
        return "committed", None
    status = str(item.get("status") or "")
    missing_kind = str(item.get("missing_kind") or "")
    if status in {"applied", "unchanged"}:
        return "committed", None
    if status == "missing" and missing_kind == "removed":
        return "removed", None
    if status == "missing" and missing_kind == "absent":
        return "transient", _CLONE_LAG_DETAIL
    if status == "missing":
        return "transient", _CLONE_LAG_DETAIL
    return "transient", f"unexpected projection status {status or 'unknown'}"


def _is_this_store(
    route_store: object,
    local: BeadTargetStoreDescriptor,
) -> bool:
    project_key = getattr(route_store, "project_key", None)
    if local.project_key and project_key == local.project_key:
        return True
    beads_dir = getattr(route_store, "beads_dir", None)
    if beads_dir is not None and local.beads_dir is not None:
        return Path(beads_dir).expanduser().resolve(
            strict=False
        ) == local.beads_dir.expanduser().resolve(strict=False)
    return getattr(route_store, "store_key", None) == local.store_key


def _canonical_beads_dir(
    store: ArtifactLinkStore,
    snapshots: Sequence[BeadStoreSnapshot],
) -> Path | None:
    for snapshot in snapshots:
        if snapshot.origin.project_key != store.project_key:
            continue
        if snapshot.origin.beads_dir is None:
            continue
        return snapshot.origin.beads_dir.expanduser().resolve(strict=False)
    return None


def _stored_issue_prefix(beads_dir: Path) -> str | None:
    try:
        payload = json.loads((beads_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    prefix = payload.get("issue_prefix")
    return prefix if isinstance(prefix, str) and prefix else None


__all__ = [
    "BeadEndpointEvidence",
    "classify_bead_issue_ids",
    "demote_committed_evidence",
    "evidence_from_projection_chunk",
    "keep_worse_evidence",
    "partition_local_projection_requests",
]
