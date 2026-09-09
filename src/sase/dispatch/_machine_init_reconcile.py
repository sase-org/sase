"""Reconciliation helpers for remote-machine initialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.core.machine_setup_facade import reconcile_machine_enrollments
from sase.dispatch._machine_init_types import CandidateDisposition, ReconciledCandidate
from sase.dispatch.models import DiscoveryCandidate, MachineRecord


def reconcile_candidates(
    candidates: Sequence[DiscoveryCandidate],
    enrolled: Sequence[MachineRecord],
) -> tuple[ReconciledCandidate, ...]:
    """Classify candidates against enrolled machine identity pins."""
    result = reconcile_machine_enrollments(
        {
            "schema_version": 1,
            "candidates": [_candidate_wire(candidate) for candidate in candidates],
            "enrolled": [_enrolled_wire(record) for record in enrolled],
        }
    )
    reconciled: list[ReconciledCandidate] = []
    for item in result.get("items") or ():
        if not isinstance(item, Mapping):
            continue
        raw_status = item.get("status")
        status: CandidateDisposition = (
            raw_status if raw_status in {"new", "enrolled", "repair"} else "new"
        )
        reconciled.append(
            ReconciledCandidate(
                candidate=_candidate_from_wire(item.get("candidate")),
                status=status,
                alias=str(item.get("alias") or ""),
                reason=str(item.get("reason") or ""),
            )
        )
    return tuple(reconciled)


def _candidate_wire(candidate: DiscoveryCandidate) -> dict[str, str]:
    return {
        "provider_ref": candidate.provider_ref,
        "endpoint": candidate.endpoint,
        "display_name": candidate.display_name,
        "machine_selector": candidate.machine_selector,
        "installation_pin": candidate.installation_pin,
        "detail": candidate.detail,
    }


def _enrolled_wire(record: MachineRecord) -> dict[str, str]:
    return {
        "alias": record.alias,
        "provider_ref": record.provider_ref,
        "endpoint": record.endpoint,
        "pinned_installation_id": record.pinned_installation_id,
    }


def _candidate_from_wire(raw: object) -> DiscoveryCandidate:
    payload = raw if isinstance(raw, Mapping) else {}
    return DiscoveryCandidate(
        provider_ref=str(payload.get("provider_ref") or ""),
        endpoint=str(payload.get("endpoint") or ""),
        display_name=str(payload.get("display_name") or ""),
        machine_selector=str(payload.get("machine_selector") or ""),
        installation_pin=str(payload.get("installation_pin") or ""),
        detail=str(payload.get("detail") or ""),
    )
