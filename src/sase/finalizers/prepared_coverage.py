"""Host adapter from staged monitor facts to prepared-starter coverage.

A prepared intent is sealed before the handoff descriptor exists. This
adapter loads that intent, the host-owned reservation (when the intent is
still ``prepared``), and live repository observations, then asks the Rust
predicate whether the starter's current obligations are covered.

Reservation/payload contract for the outer monitor-staging phase (persist
these facts in the staged record payload *before* publishing the staged
record; do not bind at staging time):

- ``prepared_intent_ref``: artifact ref, local ref, or intent id accepted by
  ``load_prepared_completion``.
- ``prepared_reservation``: ``{staged_id, monitor_id, request_fingerprint,
  command}`` matching :class:`PreparedReservationWire`. ``staged_id`` is the
  staged record UUID; ``command`` is the exact argv that will start; the
  intent stays in lifecycle state ``prepared`` until spawn binds it.

This module never launches, reserves, or binds ToolRuns.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import StagedHandoffError, read_staged_handoff
from sase.core.continuation_facade import evaluate_prepared_starter_coverage
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    PreparedReservationWire,
)
from sase.finalizers.declaration_store import FinalizerDeclarationError

PREPARED_RESERVATION_PAYLOAD_KEY = "prepared_reservation"
_HOST_COMPLETION_RECEIPT_FILENAME = "host_completion_receipt.json"
_HOST_COMPLETION_ACTIVE_STATUSES = frozenset(
    {"finalizing", "recovery", "needs_attention"}
)
_UNRESERVED_MONITOR_ID = "unreserved"
_UNRESERVED_FINGERPRINT = "unreserved"


@dataclass(frozen=True, slots=True)
class PreparedStarterCoverage:
    """Adapter view of one prepared-starter coverage decision."""

    eligible: bool
    covered_repository_ids: tuple[str, ...]
    reason: str | None
    reasons: tuple[str, ...]


def prepared_coverage_omits_starter_submission(
    root: Path,
    coverage: PreparedStarterCoverage,
) -> bool:
    """Return whether the starter may omit a declaration for *coverage*.

    Host completion must still be able to install the sealed commits, so an
    in-flight host-completion receipt never omits submission even when the
    predicate is eligible for the original starter identity.
    """

    return coverage.eligible and not _host_completion_is_installing(root)


def _host_completion_is_installing(root: Path) -> bool:
    """Return whether this artifacts dir is installing host completion."""

    path = Path(root) / _HOST_COMPLETION_RECEIPT_FILENAME
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    return str(payload.get("status") or "") in _HOST_COMPLETION_ACTIVE_STATUSES


def _reservation_from_staged_payload(
    payload: Mapping[str, Any] | None,
) -> PreparedReservationWire | None:
    """Parse the host-owned reservation from a staged-record payload."""

    if not isinstance(payload, Mapping):
        return None
    raw = payload.get(PREPARED_RESERVATION_PAYLOAD_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise FinalizerDeclarationError(
            "staged prepared reservation is malformed",
            code="unreadable_prepared_reservation",
        )
    staged_id = raw.get("staged_id")
    monitor_id = raw.get("monitor_id")
    fingerprint = raw.get("request_fingerprint")
    command = raw.get("command")
    if not (
        isinstance(staged_id, str)
        and staged_id.strip()
        and isinstance(monitor_id, str)
        and monitor_id.strip()
        and isinstance(fingerprint, str)
        and fingerprint.strip()
        and isinstance(command, list)
        and command
        and all(isinstance(part, str) and part for part in command)
    ):
        raise FinalizerDeclarationError(
            "staged prepared reservation is malformed",
            code="unreadable_prepared_reservation",
        )
    return PreparedReservationWire(
        staged_id=staged_id,
        monitor_id=monitor_id,
        request_fingerprint=fingerprint,
        command=[str(part) for part in command],
    )


def evaluate_prepared_starter_coverage_for_artifacts(
    root: Path,
    *,
    plan_digest: str,
    obligation_ids: Sequence[str],
    run_id: str,
    agent_id: str,
    workspace_id: str | None = None,
) -> PreparedStarterCoverage:
    """Load reservation/binding facts and evaluate the Rust predicate."""

    try:
        record = read_staged_handoff(str(root))
    except StagedHandoffError:
        return _refused("unreadable_staged_handoff")
    if record is None:
        return _refused("no_prepared_intent_ref")
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return _refused("unreadable_staged_handoff")
    intent_ref = payload.get("prepared_intent_ref")
    if not isinstance(intent_ref, str) or not intent_ref.strip():
        return _refused("no_prepared_intent_ref")

    try:
        reservation = _reservation_from_staged_payload(payload)
    except FinalizerDeclarationError as exc:
        return _refused(exc.code or "unreadable_prepared_reservation")

    try:
        intent = _load_intent(intent_ref, root)
    except FinalizerDeclarationError as exc:
        code = exc.code or "unreadable_prepared_intent"
        if code == "missing_completion_intent":
            return _refused("missing_prepared_intent")
        return _refused("unreadable_prepared_intent")
    except (OSError, ValueError, TypeError):
        return _refused("unreadable_prepared_intent")

    monitor_id, command, fingerprint = _request_identity(intent, reservation)
    observations = _live_observations(root)
    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent": intent,
        "staged_id": str(record.get("staged_id") or ""),
        "staged_kind": str(record.get("kind") or ""),
        "starter_run_id": run_id,
        "starter_agent_id": agent_id,
        "monitor_id": monitor_id,
        "command": command,
        "request_fingerprint": fingerprint,
        "current_observations": observations,
        "current_plan_digest": plan_digest,
        "current_obligation_ids": [str(item) for item in obligation_ids],
        "reservation": reservation,
    }
    if workspace_id:
        request["starter_workspace_id"] = workspace_id
    try:
        decision = evaluate_prepared_starter_coverage(request)
    except (TypeError, ValueError) as exc:
        del exc
        return _refused("invalid_prepared_coverage_request")
    reasons = tuple(str(item) for item in decision.get("reasons") or ())
    covered = tuple(str(item) for item in decision.get("covered_repository_ids") or ())
    reason = decision.get("reason")
    if reason is not None:
        reason = str(reason)
    elif reasons:
        reason = reasons[0]
    return PreparedStarterCoverage(
        eligible=bool(decision.get("eligible")),
        covered_repository_ids=covered,
        reason=reason,
        reasons=reasons,
    )


def _load_intent(reference: str, root: Path) -> dict[str, Any]:
    from sase.finalizers.prepare import load_prepared_completion

    return load_prepared_completion(reference, artifacts_dir=root)


def _live_observations(root: Path) -> list[dict[str, Any]]:
    from sase.finalizers import prepare as prepare_facade

    observed = prepare_facade.observe_completion_repositories(root)
    return [dict(item) for item in observed if isinstance(item, Mapping)]


def _request_identity(
    intent: Mapping[str, Any],
    reservation: PreparedReservationWire | None,
) -> tuple[str, list[str], str]:
    if reservation is not None:
        return (
            reservation["monitor_id"],
            list(reservation["command"]),
            reservation["request_fingerprint"],
        )
    binding = intent.get("binding")
    verification = intent.get("verification")
    command: list[str] = []
    if isinstance(verification, Mapping):
        raw_command = verification.get("command")
        if isinstance(raw_command, list):
            command = [str(part) for part in raw_command if str(part)]
    monitor_id = _UNRESERVED_MONITOR_ID
    fingerprint = _UNRESERVED_FINGERPRINT
    if isinstance(binding, Mapping):
        bound_monitor = binding.get("monitor_id")
        if isinstance(bound_monitor, str) and bound_monitor.strip():
            monitor_id = bound_monitor
        bound_fingerprint = binding.get("request_fingerprint")
        if isinstance(bound_fingerprint, str) and bound_fingerprint.strip():
            fingerprint = bound_fingerprint
        bound_command = binding.get("bound_command")
        if isinstance(bound_command, list) and bound_command:
            command = [str(part) for part in bound_command if str(part)]
    if not command:
        command = [_UNRESERVED_MONITOR_ID]
    return monitor_id, command, fingerprint


def _refused(reason: str) -> PreparedStarterCoverage:
    return PreparedStarterCoverage(
        eligible=False,
        covered_repository_ids=(),
        reason=reason,
        reasons=(reason,),
    )


__all__ = [
    "PREPARED_RESERVATION_PAYLOAD_KEY",
    "PreparedStarterCoverage",
    "evaluate_prepared_starter_coverage_for_artifacts",
    "prepared_coverage_omits_starter_submission",
]
