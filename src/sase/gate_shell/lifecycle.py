"""Deterministic, receipt-aware gate lifecycle classification.

Shared by :mod:`sase.gate_shell.reclaim`, :mod:`sase.gate_shell.cancel`, and
``sase gate show`` so every consumer recognizes "accepted, execution
incomplete" (a durable ``decision_receipt.json`` with no ``response.json``
yet) the same way. Python collects filesystem facts; the Rust policy in
``sase_core::gate_decision`` decides the disposition.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.gate_decision_facade import (
    GATE_LIFECYCLE_WIRE_SCHEMA_VERSION,
    decide_gate_lifecycle,
)
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.paths import CANCELLATION_FILENAME, RESPONSE_FILENAME

DISPOSITION_ANSWERED = "answered"
DISPOSITION_CANCELLED_TIMEOUT = "cancelled_timeout"
DISPOSITION_CANCELLED_LOST = "cancelled_lost"
DISPOSITION_CANCELLED_STOPPED = "cancelled_stopped"
DISPOSITION_ACCEPTED_UNFINISHED = "accepted_unfinished"
DISPOSITION_PENDING = "pending"
DISPOSITION_EXPIRED_REVIEW = "expired_review"
DISPOSITION_EXPIRED_GRACE = "expired_grace"


@dataclass(frozen=True)
class _GateLifecycleFacts:
    """Bundle evidence collected by the host; the policy's Python-side input."""

    gate_id: str
    request_hash: str
    now: float
    deadline: float | None
    grace_seconds: float
    has_response: bool
    cancellation_reason: str | None
    receipt: Mapping[str, Any] | None
    receipt_unreadable: bool


def collect_gate_lifecycle_facts(
    bundle: Path,
    envelope: Mapping[str, Any],
    *,
    now: float,
    deadline: float | None,
    grace_seconds: float,
) -> _GateLifecycleFacts:
    """Read one gate bundle's terminal and acceptance evidence from disk."""
    has_response = (bundle / RESPONSE_FILENAME).exists()

    cancellation_reason: str | None = None
    cancellation_path = bundle / CANCELLATION_FILENAME
    if cancellation_path.exists():
        cancellation = _read_json_or_none(cancellation_path)
        cancellation_reason = str((cancellation or {}).get("reason") or "") or None

    receipt: Mapping[str, Any] | None = None
    receipt_unreadable = False
    receipt_path = bundle / DECISION_RECEIPT_FILENAME
    if receipt_path.exists():
        receipt = _read_json_or_none(receipt_path)
        receipt_unreadable = receipt is None

    return _GateLifecycleFacts(
        gate_id=str(envelope["request_id"]),
        request_hash=str(envelope["hashes"]["request"]),
        now=now,
        deadline=deadline,
        grace_seconds=grace_seconds,
        has_response=has_response,
        cancellation_reason=cancellation_reason,
        receipt=receipt,
        receipt_unreadable=receipt_unreadable,
    )


def _read_json_or_none(path: Path) -> dict[str, Any] | None:
    try:
        return read_json_object(path)
    except Exception:
        return None


def classify_gate_lifecycle(facts: _GateLifecycleFacts) -> dict[str, Any]:
    """Return the deterministic lifecycle disposition for one gate's facts.

    Raises ``ValueError`` when ``facts.receipt`` is unreadable or names a
    different gate or request -- see
    :func:`sase.core.gate_decision_facade.decide_gate_lifecycle`.
    """
    request: dict[str, Any] = {
        "schema_version": GATE_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "gate_id": facts.gate_id,
        "request_hash": facts.request_hash,
        "now_unix": facts.now,
        "grace_seconds": facts.grace_seconds,
        "has_response": facts.has_response,
        "receipt_unreadable": facts.receipt_unreadable,
    }
    if facts.deadline is not None:
        request["deadline_unix"] = facts.deadline
    if facts.cancellation_reason is not None:
        request["cancellation_reason"] = facts.cancellation_reason
    if facts.receipt is not None:
        request["receipt"] = dict(facts.receipt)
    return decide_gate_lifecycle(request)


def resolve_already_answered_race(bundle: Path, gate_id: str) -> str:
    """Return the disposition after ``cancel_gate`` raises ``already_answered``.

    ``cancel_gate`` only raises that error once ``response.json`` or
    ``decision_receipt.json`` exists, so a fresh classification (deadline
    math is irrelevant -- both evidence kinds outrank it) can only land on
    :data:`DISPOSITION_ANSWERED` or :data:`DISPOSITION_ACCEPTED_UNFINISHED`.
    """
    envelope, _adapter = load_and_verify_bundle(bundle)
    facts = collect_gate_lifecycle_facts(
        bundle, envelope, now=time.time(), deadline=None, grace_seconds=0.0
    )
    disposition = str(classify_gate_lifecycle(facts)["disposition"])
    if disposition in (DISPOSITION_ANSWERED, DISPOSITION_ACCEPTED_UNFINISHED):
        return disposition
    raise RuntimeError(
        f"gate {gate_id} raced to unexpected disposition {disposition!r} "
        "after an already-answered cancel"
    )


__all__ = [
    "DISPOSITION_ACCEPTED_UNFINISHED",
    "DISPOSITION_ANSWERED",
    "DISPOSITION_CANCELLED_LOST",
    "DISPOSITION_CANCELLED_STOPPED",
    "DISPOSITION_CANCELLED_TIMEOUT",
    "DISPOSITION_EXPIRED_GRACE",
    "DISPOSITION_EXPIRED_REVIEW",
    "DISPOSITION_PENDING",
    "classify_gate_lifecycle",
    "collect_gate_lifecycle_facts",
    "resolve_already_answered_race",
]
