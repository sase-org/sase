"""Host-owned prepared-intent reservation store for staged monitors.

A sealed intent stays in ``prepared`` lifecycle state while a host-owned
reservation associates it with one staged monitor. Ownership is persisted
separately from the sealed intent, under the existing completion-intents
store lock, keyed by canonical intent id. Rust owns identity and
transition legality (via ``evaluate_prepared_reservation_access``); this
module owns the file/lock operations.

Binding at staging time is forbidden: reserve before publishing the staged
record, bind once at spawn, release on discard. Another stage or an
immediate start cannot steal the intent; matching cleanup may release it.
"""

from __future__ import annotations

from collections.abc import Mapping
import fcntl
import json
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import evaluate_prepared_reservation_access
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    PreparedReservationWire,
    StoredPreparedReservationWire,
)
from sase.finalizers._prepare_intents import (
    COMPLETION_INTENTS_DIRNAME,
    COMPLETION_LOCK_FILENAME,
    resolve_intent_path,
)
from sase.finalizers.declaration import require_artifacts_dir
from sase.finalizers.declaration_store import write_json_atomic
from sase.memory.locks import locked_file

RESERVATIONS_FILENAME = "reservations.json"

_MISSING_INTENT_CODE = "missing_completion_intent"
_CONFLICT_CODE = "prepared_reservation_conflict"


def load_prepared_intent_reservations(
    *,
    artifacts_dir: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return intent-id-keyed prepared reservations for one artifacts dir."""

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "prepared reservation read",
    )
    with _reservations_lock(root):
        stored = read_prepared_reservations_locked(root)
    reservations: dict[str, dict[str, Any]] = {}
    if not isinstance(stored, Mapping):
        return reservations
    for intent_id, record in stored.items():
        if isinstance(intent_id, str) and isinstance(record, dict):
            reservations[intent_id] = dict(record)
    return reservations


def reserve_prepared_intent(
    reference: str,
    reservation: Mapping[str, Any],
    *,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Reserve one sealed intent for a staged monitor; never steals.

    Raises :class:`FinalizerDeclarationError` when another stage holds the
    intent or the reservation fails the Rust ownership check.
    """

    from sase.finalizers.declaration import FinalizerDeclarationError

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "prepared reservation reserve",
    )
    record = {
        "intent_ref": "",
        "reservation": dict(reservation),
    }
    with _reservations_lock(root):
        intent_id = canonical_prepared_intent_id(root, reference)
        record["intent_ref"] = intent_id
        stored = read_prepared_reservations_locked(root)
        existing = existing_prepared_reservation_wires(stored)
        reservation_wire = _reservation_wire(reservation)

        # Run the same Rust transition validator used at bind time against
        # the sealed intent and exact argv. This is a pure in-memory
        # transition check: the file remains in `prepared` state until the
        # adopter binds it immediately before spawn.
        from sase.core.continuation_facade import bind_conditional_completion
        from sase.finalizers._prepare_intents import (
            validate_conditional_completion_intent,
        )

        try:
            intent_path = resolve_intent_path(root, intent_id)
            raw_intent = json.loads(intent_path.read_text(encoding="utf-8"))
            intent = validate_conditional_completion_intent(raw_intent)
            bind_conditional_completion(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "intent": intent,
                    "monitor_id": reservation_wire["monitor_id"],
                    "command": reservation_wire["command"],
                    "request_fingerprint": reservation_wire["request_fingerprint"],
                }
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise FinalizerDeclarationError(
                f"prepared intent {intent_id!r} could not be validated ({exc})",
                code="invalid_prepared_intent",
            ) from exc
        except ValueError as exc:
            raise FinalizerDeclarationError(
                str(exc), code="invalid_prepared_intent"
            ) from exc

        decision = evaluate_prepared_reservation_access(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent_ref": intent_id,
                "staged_id": reservation_wire["staged_id"],
                "monitor_id": reservation_wire["monitor_id"],
                "action": "reserve",
                "existing": existing,
            }
        )
        if not decision.get("allowed"):
            raise FinalizerDeclarationError(
                f"prepared intent {intent_id!r} is held by another stage "
                f"({decision.get('reason') or 'reserved'})",
                code=_CONFLICT_CODE,
            )
        incumbent = stored.get(intent_id)
        if isinstance(incumbent, Mapping):
            incumbent_reservation = incumbent.get("reservation")
            if not isinstance(incumbent_reservation, Mapping) or dict(
                incumbent_reservation
            ) != dict(reservation):
                raise FinalizerDeclarationError(
                    f"prepared intent {intent_id!r} is already reserved with "
                    "different monitor inputs",
                    code=_CONFLICT_CODE,
                )
        stored[intent_id] = record
        _write_reservations(root, stored)
    return {str(key): value for key, value in record.items()}


def release_prepared_intent(
    reference: str,
    *,
    staged_id: str,
    monitor_id: str,
    artifacts_dir: str | Path | None = None,
) -> bool:
    """Release one stage's prepared reservation; idempotent.

    Returns whether a reservation was removed. Raises
    :class:`FinalizerDeclarationError` when another stage holds the intent.
    """

    from sase.finalizers.declaration import FinalizerDeclarationError

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "prepared reservation release",
    )
    with _reservations_lock(root):
        intent_id = canonical_prepared_intent_id(root, reference)
        stored = read_prepared_reservations_locked(root)
        existing = existing_prepared_reservation_wires(stored)
        decision = evaluate_prepared_reservation_access(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent_ref": intent_id,
                "staged_id": staged_id,
                "monitor_id": monitor_id,
                "action": "release",
                "existing": existing,
            }
        )
        if not decision.get("allowed"):
            raise FinalizerDeclarationError(
                f"prepared intent {intent_id!r} is held by another stage "
                f"({decision.get('reason') or 'reserved'})",
                code=_CONFLICT_CODE,
            )
        incumbent = stored.get(intent_id)
        if incumbent is None:
            return False
        reservation = (
            incumbent.get("reservation") if isinstance(incumbent, Mapping) else None
        )
        if not isinstance(reservation, Mapping) or (
            reservation.get("staged_id") != staged_id
            or reservation.get("monitor_id") != monitor_id
        ):
            raise FinalizerDeclarationError(
                f"prepared intent {intent_id!r} is held by another stage",
                code=_CONFLICT_CODE,
            )
        del stored[intent_id]
        _write_reservations(root, stored)
        return True


def _reservations_dir(root: Path) -> Path:
    directory = root / "continuation" / COMPLETION_INTENTS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _reservations_lock(root: Path) -> Any:
    directory = _reservations_dir(root)
    return locked_file(directory / COMPLETION_LOCK_FILENAME, fcntl.LOCK_EX)


def _reservations_path(root: Path) -> Path:
    return _reservations_dir(root) / RESERVATIONS_FILENAME


def read_prepared_reservations_locked(root: Path) -> dict[str, Any]:
    from sase.finalizers.declaration import FinalizerDeclarationError

    path = _reservations_path(root)
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizerDeclarationError(
            f"prepared intent reservations are unreadable at {path}",
            code="unreadable_prepared_reservations",
        ) from exc
    wrappers = loaded.get("reservations") if isinstance(loaded, dict) else None
    if not isinstance(wrappers, dict):
        raise FinalizerDeclarationError(
            f"prepared intent reservations are malformed at {path}",
            code="unreadable_prepared_reservations",
        )
    for intent_id, record in wrappers.items():
        if (
            not isinstance(intent_id, str)
            or not intent_id.strip()
            or not isinstance(record, Mapping)
            or record.get("intent_ref") != intent_id
            or not isinstance(record.get("reservation"), Mapping)
        ):
            raise FinalizerDeclarationError(
                f"prepared intent reservation entry is malformed at {path}",
                code="unreadable_prepared_reservations",
            )
        try:
            _reservation_wire(record["reservation"])
        except (TypeError, ValueError) as exc:
            raise FinalizerDeclarationError(
                f"prepared intent reservation entry is malformed at {path}",
                code="unreadable_prepared_reservations",
            ) from exc
    return dict(wrappers)


def _write_reservations(root: Path, stored: dict[str, Any]) -> None:
    write_json_atomic(_reservations_path(root), {"reservations": stored})


def existing_prepared_reservation_wires(
    stored: Mapping[str, Any],
) -> list[StoredPreparedReservationWire]:
    existing: list[StoredPreparedReservationWire] = []
    for intent_id, record in stored.items():
        if not isinstance(record, dict):
            continue
        reservation = _reservation_wire(record["reservation"])
        existing.append(
            StoredPreparedReservationWire(
                intent_ref=str(intent_id),
                reservation=reservation,
            )
        )
    return existing


def _reservation_wire(reservation: Mapping[str, Any]) -> PreparedReservationWire:
    """Parse one persisted reservation without normalizing away corruption."""

    staged_id = reservation.get("staged_id")
    monitor_id = reservation.get("monitor_id")
    fingerprint = reservation.get("request_fingerprint")
    command = reservation.get("command")
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
        and set(reservation)
        == {"staged_id", "monitor_id", "request_fingerprint", "command"}
    ):
        raise ValueError("prepared reservation is malformed")
    return PreparedReservationWire(
        staged_id=staged_id,
        monitor_id=monitor_id,
        request_fingerprint=fingerprint,
        command=list(command),
    )


def canonical_prepared_intent_id(root: Path, reference: str) -> str:
    """Resolve *reference* to the indexed intent id; fail closed otherwise."""

    from sase.finalizers.declaration import FinalizerDeclarationError

    directory = _reservations_dir(root)
    index_path = directory / "index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            index = {}
        if isinstance(index, dict):
            aliases = index.get("aliases")
            if isinstance(aliases, dict) and reference in aliases:
                return str(aliases[reference])
            intents = index.get("intents")
            if isinstance(intents, dict) and reference in intents:
                return str(reference)
    raise FinalizerDeclarationError(
        f"conditional completion intent {reference!r} was not found",
        code=_MISSING_INTENT_CODE,
    )
