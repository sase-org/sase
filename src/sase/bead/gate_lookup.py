"""Shared lookup for pending bead notification gates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    REQUEST_FILENAME,
    RESPONSE_FILENAME,
    interaction_requests_dir,
)


@dataclass(frozen=True)
class _PendingBeadGate:
    """Trusted identity for one pending bead-related gate."""

    kind: str
    request_id: str
    project: str
    bead_id: str
    producer_chop: str | None


def find_pending_bead_gates(kinds: Iterable[str]) -> list[_PendingBeadGate]:
    """Return pending bead gate identities for *kinds* in deterministic order."""
    results: list[_PendingBeadGate] = []
    for kind in sorted(set(kinds)):
        if not kind:
            continue
        results.extend(_pending_bead_gates_for_kind(kind))
    return sorted(
        results,
        key=lambda gate: (
            gate.kind,
            gate.request_id,
            gate.project,
            gate.bead_id,
            gate.producer_chop or "",
        ),
    )


def _pending_bead_gates_for_kind(kind: str) -> list[_PendingBeadGate]:
    from sase.notification_gates.durability import read_json_object

    kind_dir = interaction_requests_dir() / kind
    try:
        bundles = sorted(kind_dir.iterdir(), key=lambda path: path.name)
    except (FileNotFoundError, OSError):
        return []

    gates: list[_PendingBeadGate] = []
    for bundle in bundles:
        if not bundle.is_dir():
            continue
        if (bundle / RESPONSE_FILENAME).exists() or (
            bundle / CANCELLATION_FILENAME
        ).exists():
            continue
        try:
            envelope = read_json_object(bundle / REQUEST_FILENAME)
        except GateError:
            continue
        gate = _pending_bead_gate_from_envelope(envelope)
        if gate is not None and gate.kind == kind:
            gates.append(gate)
    return gates


def _pending_bead_gate_from_envelope(
    envelope: Mapping[str, object],
) -> _PendingBeadGate | None:
    kind = envelope.get("kind")
    request_id = envelope.get("request_id")
    payload = envelope.get("payload")
    if not (
        isinstance(kind, str)
        and kind
        and isinstance(request_id, str)
        and request_id
        and isinstance(payload, Mapping)
    ):
        return None
    project = payload.get("project")
    bead_id = payload.get("bead_id")
    if not (
        isinstance(project, str) and project and isinstance(bead_id, str) and bead_id
    ):
        return None
    producer = envelope.get("producer")
    producer_chop = None
    if isinstance(producer, Mapping):
        chop = producer.get("chop")
        if isinstance(chop, str) and chop:
            producer_chop = chop
    return _PendingBeadGate(
        kind=kind,
        request_id=request_id,
        project=project,
        bead_id=bead_id,
        producer_chop=producer_chop,
    )


__all__ = ["find_pending_bead_gates"]
