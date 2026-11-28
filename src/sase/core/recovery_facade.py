"""Python facade for sase-core recovery activation and claim records.

Frozen dataclasses mirror the recovery wires. Host adapters gather store
paths and caller identity, then call through these helpers; the Rust
binding owns validation, deterministic keys, create-if-absent writes, and
malformed-record diagnostics.

Bindings are looked up with
:func:`~sase.core.rust.optional_rust_binding` so one tree keeps working
against older cores: callers treat a missing binding as an explicit
unavailable result instead of crashing when the installed wheel predates
the recovery contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.rust import optional_rust_binding

RECOVERY_WIRE_SCHEMA_VERSION = 1
RECOVERY_STATE_ABSENT = "absent"
RECOVERY_STATE_ARMED = "armed"
RECOVERY_STATE_PRESENT = "present"
RECOVERY_STATE_CREATED = "created"
RECOVERY_STATE_EXISTING = "existing"
RECOVERY_STATE_MALFORMED = "malformed"
RECOVERY_STATE_REFUSED = "refused"
RECOVERY_UNKNOWN_UNSUPPORTED_CORE = "unsupported_core_binding"

_CLAIM_KEY_BINDING = "bead_recovery_claim_key"
_INSPECT_ACTIVATION_BINDING = "bead_recovery_inspect_activation"
_ARM_ACTIVATION_BINDING = "bead_recovery_arm_activation"
_INSPECT_CLAIM_BINDING = "bead_recovery_inspect_claim"
_CREATE_CLAIM_BINDING = "bead_recovery_create_claim"
_INSPECT_STORE_BINDING = "bead_recovery_inspect_store"


@dataclass(frozen=True, slots=True)
class RecoveryActivation:
    """Versioned project activation / rollout cutoff."""

    project_id: str
    armed_at: str
    generation: int
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryClaim:
    """Durable claim for one project/epic/close-token key."""

    project_id: str
    epic_id: str
    close_token: str
    owner_machine: str
    proc_id: str
    request_fingerprint: str
    activation_generation: int
    created_at: str
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryActivationInspect:
    """Read-only activation inspection."""

    project_id: str
    state: str
    recovery_enabled: bool
    activation: RecoveryActivation | None = None
    diagnostic: str | None = None
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryArmResult:
    """Create-if-absent arming outcome."""

    state: str
    created: bool
    recovery_enabled: bool
    activation: RecoveryActivation | None = None
    diagnostic: str | None = None
    lock_wait_ms: int = 0
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryClaimInspect:
    """Read-only claim inspection."""

    claim_key: str
    project_id: str
    epic_id: str
    close_token: str
    state: str
    claim: RecoveryClaim | None = None
    diagnostic: str | None = None
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryClaimCreateResult:
    """Create-if-absent claim outcome for the local store."""

    claim_key: str
    state: str
    created: bool
    local_winner: bool
    claim: RecoveryClaim | None = None
    diagnostic: str | None = None
    lock_wait_ms: int = 0
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryStoreInspect:
    """Activation plus every claim in one project's recovery namespace."""

    activation: RecoveryActivationInspect
    claims: tuple[RecoveryClaimInspect, ...] = ()
    schema_version: int = RECOVERY_WIRE_SCHEMA_VERSION


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_bool(value: object, default: bool = False) -> bool:
    return bool(value) if isinstance(value, bool) else default


def _optional_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _unsupported(operation: str) -> RuntimeError:
    return RuntimeError(
        f"sase_core_rs does not expose {operation}; the installed wheel "
        "predates the recovery-claim contract"
    )


def _require_mapping(raw: object, operation: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuntimeError(f"sase_core_rs {operation} returned a non-mapping result")
    return raw


def _activation_from_wire(raw: object) -> RecoveryActivation | None:
    if not isinstance(raw, Mapping):
        return None
    project_id = _optional_str(raw.get("project_id"))
    armed_at = _optional_str(raw.get("armed_at"))
    generation = _optional_int(raw.get("generation"))
    if not project_id or not armed_at or generation < 1:
        return None
    return RecoveryActivation(
        project_id=project_id,
        armed_at=armed_at,
        generation=generation,
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


def _claim_from_wire(raw: object) -> RecoveryClaim | None:
    if not isinstance(raw, Mapping):
        return None
    project_id = _optional_str(raw.get("project_id"))
    epic_id = _optional_str(raw.get("epic_id"))
    close_token = _optional_str(raw.get("close_token"))
    owner_machine = _optional_str(raw.get("owner_machine"))
    proc_id = _optional_str(raw.get("proc_id"))
    request_fingerprint = _optional_str(raw.get("request_fingerprint"))
    created_at = _optional_str(raw.get("created_at"))
    generation = _optional_int(raw.get("activation_generation"))
    if (
        project_id is None
        or epic_id is None
        or close_token is None
        or owner_machine is None
        or proc_id is None
        or request_fingerprint is None
        or created_at is None
    ):
        return None
    if generation < 1:
        return None
    return RecoveryClaim(
        project_id=project_id,
        epic_id=epic_id,
        close_token=close_token,
        owner_machine=owner_machine,
        proc_id=proc_id,
        request_fingerprint=request_fingerprint,
        activation_generation=generation,
        created_at=created_at,
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


def recovery_claim_key(project_id: str, epic_id: str, close_token: str) -> str:
    """Return the deterministic claim key, or raise when the core is too old."""
    binding = optional_rust_binding(_CLAIM_KEY_BINDING)
    if binding is None:
        raise _unsupported(_CLAIM_KEY_BINDING)
    key = binding(project_id, epic_id, close_token)
    if not isinstance(key, str) or not key:
        raise RuntimeError("sase_core_rs bead_recovery_claim_key returned no key")
    return key


def inspect_recovery_activation(
    beads_dir: str, project_id: str
) -> RecoveryActivationInspect:
    """Inspect the project activation record in *beads_dir*."""
    binding = optional_rust_binding(_INSPECT_ACTIVATION_BINDING)
    if binding is None:
        return RecoveryActivationInspect(
            project_id=project_id,
            state=RECOVERY_STATE_MALFORMED,
            recovery_enabled=False,
            diagnostic=RECOVERY_UNKNOWN_UNSUPPORTED_CORE,
        )
    raw = _require_mapping(binding(beads_dir, project_id), _INSPECT_ACTIVATION_BINDING)
    return RecoveryActivationInspect(
        project_id=_optional_str(raw.get("project_id")) or project_id,
        state=_optional_str(raw.get("state")) or RECOVERY_STATE_MALFORMED,
        recovery_enabled=_optional_bool(raw.get("recovery_enabled")),
        activation=_activation_from_wire(raw.get("activation")),
        diagnostic=_optional_str(raw.get("diagnostic")),
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


def arm_recovery_activation(
    beads_dir: str, request: Mapping[str, Any]
) -> RecoveryArmResult:
    """Create-if-absent arm the project activation record."""
    binding = optional_rust_binding(_ARM_ACTIVATION_BINDING)
    if binding is None:
        return RecoveryArmResult(
            state=RECOVERY_STATE_REFUSED,
            created=False,
            recovery_enabled=False,
            diagnostic=RECOVERY_UNKNOWN_UNSUPPORTED_CORE,
        )
    raw = _require_mapping(binding(beads_dir, dict(request)), _ARM_ACTIVATION_BINDING)
    return RecoveryArmResult(
        state=_optional_str(raw.get("state")) or RECOVERY_STATE_REFUSED,
        created=_optional_bool(raw.get("created")),
        recovery_enabled=_optional_bool(raw.get("recovery_enabled")),
        activation=_activation_from_wire(raw.get("activation")),
        diagnostic=_optional_str(raw.get("diagnostic")),
        lock_wait_ms=_optional_int(raw.get("lock_wait_ms")),
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


def inspect_recovery_claim(
    beads_dir: str, request: Mapping[str, Any]
) -> RecoveryClaimInspect:
    """Inspect one recovery claim in *beads_dir*."""
    binding = optional_rust_binding(_INSPECT_CLAIM_BINDING)
    if binding is None:
        return RecoveryClaimInspect(
            claim_key="",
            project_id=str(request.get("project_id") or ""),
            epic_id=str(request.get("epic_id") or ""),
            close_token=str(request.get("close_token") or ""),
            state=RECOVERY_STATE_MALFORMED,
            diagnostic=RECOVERY_UNKNOWN_UNSUPPORTED_CORE,
        )
    raw = _require_mapping(binding(beads_dir, dict(request)), _INSPECT_CLAIM_BINDING)
    return RecoveryClaimInspect(
        claim_key=_optional_str(raw.get("claim_key")) or "",
        project_id=_optional_str(raw.get("project_id")) or "",
        epic_id=_optional_str(raw.get("epic_id")) or "",
        close_token=_optional_str(raw.get("close_token")) or "",
        state=_optional_str(raw.get("state")) or RECOVERY_STATE_MALFORMED,
        claim=_claim_from_wire(raw.get("claim")),
        diagnostic=_optional_str(raw.get("diagnostic")),
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


def create_recovery_claim(
    beads_dir: str, request: Mapping[str, Any]
) -> RecoveryClaimCreateResult:
    """Create-if-absent a recovery claim in the local store."""
    binding = optional_rust_binding(_CREATE_CLAIM_BINDING)
    if binding is None:
        return RecoveryClaimCreateResult(
            claim_key="",
            state=RECOVERY_STATE_REFUSED,
            created=False,
            local_winner=False,
            diagnostic=RECOVERY_UNKNOWN_UNSUPPORTED_CORE,
        )
    raw = _require_mapping(binding(beads_dir, dict(request)), _CREATE_CLAIM_BINDING)
    return RecoveryClaimCreateResult(
        claim_key=_optional_str(raw.get("claim_key")) or "",
        state=_optional_str(raw.get("state")) or RECOVERY_STATE_REFUSED,
        created=_optional_bool(raw.get("created")),
        local_winner=_optional_bool(raw.get("local_winner")),
        claim=_claim_from_wire(raw.get("claim")),
        diagnostic=_optional_str(raw.get("diagnostic")),
        lock_wait_ms=_optional_int(raw.get("lock_wait_ms")),
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


def inspect_recovery_store(beads_dir: str, project_id: str) -> RecoveryStoreInspect:
    """Inspect the recovery namespace for *project_id*."""
    binding = optional_rust_binding(_INSPECT_STORE_BINDING)
    if binding is None:
        return RecoveryStoreInspect(
            activation=RecoveryActivationInspect(
                project_id=project_id,
                state=RECOVERY_STATE_MALFORMED,
                recovery_enabled=False,
                diagnostic=RECOVERY_UNKNOWN_UNSUPPORTED_CORE,
            )
        )
    raw = _require_mapping(binding(beads_dir, project_id), _INSPECT_STORE_BINDING)
    claims_raw = raw.get("claims")
    claims: list[RecoveryClaimInspect] = []
    if isinstance(claims_raw, list):
        for item in claims_raw:
            if not isinstance(item, Mapping):
                continue
            claims.append(
                RecoveryClaimInspect(
                    claim_key=_optional_str(item.get("claim_key")) or "",
                    project_id=_optional_str(item.get("project_id")) or "",
                    epic_id=_optional_str(item.get("epic_id")) or "",
                    close_token=_optional_str(item.get("close_token")) or "",
                    state=_optional_str(item.get("state")) or RECOVERY_STATE_MALFORMED,
                    claim=_claim_from_wire(item.get("claim")),
                    diagnostic=_optional_str(item.get("diagnostic")),
                    schema_version=_optional_int(
                        item.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
                    ),
                )
            )
    activation_raw = raw.get("activation")
    if isinstance(activation_raw, Mapping):
        activation = RecoveryActivationInspect(
            project_id=_optional_str(activation_raw.get("project_id")) or project_id,
            state=_optional_str(activation_raw.get("state"))
            or RECOVERY_STATE_MALFORMED,
            recovery_enabled=_optional_bool(activation_raw.get("recovery_enabled")),
            activation=_activation_from_wire(activation_raw.get("activation")),
            diagnostic=_optional_str(activation_raw.get("diagnostic")),
            schema_version=_optional_int(
                activation_raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
            ),
        )
    else:
        activation = RecoveryActivationInspect(
            project_id=project_id,
            state=RECOVERY_STATE_MALFORMED,
            recovery_enabled=False,
            diagnostic="recovery store activation is not a mapping",
        )
    return RecoveryStoreInspect(
        activation=activation,
        claims=tuple(claims),
        schema_version=_optional_int(
            raw.get("schema_version"), RECOVERY_WIRE_SCHEMA_VERSION
        ),
    )


__all__ = [
    "RECOVERY_STATE_ABSENT",
    "RECOVERY_STATE_ARMED",
    "RECOVERY_STATE_CREATED",
    "RECOVERY_STATE_EXISTING",
    "RECOVERY_STATE_MALFORMED",
    "RECOVERY_STATE_PRESENT",
    "RECOVERY_STATE_REFUSED",
    "RECOVERY_UNKNOWN_UNSUPPORTED_CORE",
    "RECOVERY_WIRE_SCHEMA_VERSION",
    "RecoveryActivation",
    "RecoveryActivationInspect",
    "RecoveryArmResult",
    "RecoveryClaim",
    "RecoveryClaimCreateResult",
    "RecoveryClaimInspect",
    "RecoveryStoreInspect",
    "arm_recovery_activation",
    "create_recovery_claim",
    "inspect_recovery_activation",
    "inspect_recovery_claim",
    "inspect_recovery_store",
    "recovery_claim_key",
]
