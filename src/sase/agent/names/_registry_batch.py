"""Bulk reservation transactions for the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from sase.agent.names._common import NameCollisionError
from sase.agent.names._registry_entries import entry_belongs_to_artifact
from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations,
    local_artifact_entry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    current_owner_agent_name_lookup_candidates,
)
from sase.core.agent_ownership_facade import (
    agent_ownership_batch_wire_schema_version,
    plan_agent_ownership_batch,
)

RegistryReservationOperation = Literal[
    "reserve_planned",
    "claim_planned",
    "reserve_clan",
    "claim_clan",
    "convert_family",
    "reserve_template",
    "release_planned",
    "release_planned_clan",
    "cleanup_guard",
]

_MUTATING_MERGE_ACTIONS = {"upsert", "remove"}
_PLANNED_RESERVATION_KINDS = {"planned"}
_OWNED_AGENT_RESERVATION_KINDS = {"planned", "claimed"}


class _RegistryLoader(Protocol):
    def __call__(self, *, trust_stale_proof_memo: bool = True) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RegisteredNameRegistryBatchHooks:
    """Registry internals needed to apply a planned batch."""

    mutation_lock: Callable[[], AbstractContextManager[None]]
    mutation_operations: Callable[[], RegistryMutationOperations]
    load_name_registry: _RegistryLoader
    registry_path: Callable[[], Path]
    read_registry: Callable[[Path], dict[str, Any] | None]
    save_entries_locked: Callable[[dict[str, Any]], None]
    registry_file_is_stale: Callable[[dict[str, Any]], bool]
    file_signature: Callable[[Path], tuple[int, int]]
    reset_scan_caches: Callable[[], None]


@dataclass(frozen=True)
class RegisteredNameReservation:
    """One core-planned registry reservation request."""

    request_id: str
    operation: RegistryReservationOperation
    name: str
    artifact_dir: str | Path
    namespace: str | None = None
    member_name: str | None = None
    clan_generation: str | None = None
    create_only: bool = False
    replace_existing: bool = False
    allowed_existing_names: Collection[str] = ()
    cleanup_token: str | None = None
    expected_owner: Mapping[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]:
        """Return this request in the core ownership-batch wire shape."""
        artifact_dir = Path(self.artifact_dir).expanduser().resolve(strict=False)
        wire: dict[str, Any] = {
            "request_id": self.request_id,
            "operation": self.operation,
            "name": self.name,
            "artifact_dir": str(artifact_dir),
        }
        if self.namespace is not None:
            wire["namespace"] = self.namespace
        if self.member_name is not None:
            wire["member_name"] = self.member_name
        if self.clan_generation is not None:
            wire["clan_generation"] = self.clan_generation
        if self.create_only:
            wire["create_only"] = True
        if self.replace_existing:
            wire["replace_existing"] = True
        if self.allowed_existing_names:
            wire["allowed_existing_names"] = list(self.allowed_existing_names)
        if self.cleanup_token is not None:
            wire["cleanup_token"] = self.cleanup_token
        if self.expected_owner is not None:
            wire["expected_owner"] = dict(self.expected_owner)
        if self.operation in {"reserve_planned", "reserve_template"}:
            wire["reserved_at"] = datetime.now(UTC).isoformat()
        return wire


@dataclass(frozen=True)
class RegisteredNameReservationSnapshot:
    """One fresh registry view for in-memory reservation lookups."""

    data: Mapping[str, Any]
    identity: AgentIdentitySnapshot
    registry_file_signature: tuple[int, int] | None
    source_signature: Mapping[str, int | str] | None

    @property
    def entries(self) -> Mapping[str, Mapping[str, Any]]:
        """Return registry entries keyed by durable name."""
        raw_entries = self.data.get("entries", {})
        if not isinstance(raw_entries, dict):
            return {}
        return {
            name: entry
            for name, entry in raw_entries.items()
            if isinstance(name, str) and isinstance(entry, dict)
        }

    def lookup(self, name: str) -> dict[str, Any] | None:
        """Return one entry from this snapshot without reloading the registry."""
        for candidate in current_owner_agent_name_lookup_candidates(
            name, self.identity
        ):
            entry = self.entries.get(candidate)
            if isinstance(entry, dict):
                return dict(entry)
        return None

    def reserved_agent_names(self) -> set[str]:
        """Return all names in this snapshot."""
        return set(self.entries)

    def reserved_clan_names(self) -> set[str]:
        """Return clan container names in this snapshot."""
        return {
            name
            for name, entry in self.entries.items()
            if entry.get("container_kind") == "clan"
        }

    def reserved_family_names(self) -> set[str]:
        """Return family container names in this snapshot."""
        return {
            name
            for name, entry in self.entries.items()
            if entry.get("container_kind") == "family"
        }


@dataclass(frozen=True)
class RegisteredNameReservationBatchResult:
    """Applied or no-op reservation-batch plan."""

    accepted: tuple[Mapping[str, Any], ...]
    blocked: tuple[Mapping[str, Any], ...]
    registry_merge_plan: tuple[Mapping[str, Any], ...]
    cleanup_reservations: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[str, ...]
    raw_plan: Mapping[str, Any]


class RegisteredNameReservationBatchError(NameCollisionError):
    """Raised when any reservation in a batch is blocked."""

    def __init__(self, blocked: Sequence[Mapping[str, Any]]) -> None:
        self.blocked = tuple(dict(item) for item in blocked)
        super().__init__(_format_blocked_reservations(self.blocked))


class RegisteredNameReservationRetryError(RuntimeError):
    """Raised when concurrent registry changes keep invalidating a batch."""


def registered_name_reservation_snapshot(
    hooks: RegisteredNameRegistryBatchHooks,
) -> RegisteredNameReservationSnapshot:
    """Load one fresh registry snapshot for bounded reservation work."""

    hooks.reset_scan_caches()
    data = hooks.load_name_registry(trust_stale_proof_memo=False)
    path = hooks.registry_path()
    try:
        file_signature = hooks.file_signature(path)
    except OSError:
        file_signature = None
    source_signature = data.get("source_signature")
    return RegisteredNameReservationSnapshot(
        data=data,
        identity=AgentIdentitySnapshot.current(),
        registry_file_signature=file_signature,
        source_signature=(
            source_signature if isinstance(source_signature, Mapping) else None
        ),
    )


def mutate_registered_name_reservations(
    hooks: RegisteredNameRegistryBatchHooks,
    reservations: Sequence[RegisteredNameReservation | Mapping[str, Any]],
    *,
    max_retries: int = 3,
) -> RegisteredNameReservationBatchResult:
    """Plan and apply registry reservations as one guarded transaction."""
    materialized = tuple(_coerce_reservation(item) for item in reservations)
    if not materialized:
        return _result_from_plan(
            {
                "schema_version": agent_ownership_batch_wire_schema_version(),
                "reservation_decisions": [],
                "reservation_blocked": [],
                "registry_merge_plan": [],
                "cleanup_reservations": [],
                "diagnostics": [],
            }
        )

    attempts = max(1, max_retries)
    for _attempt in range(attempts):
        snapshot = registered_name_reservation_snapshot(hooks)
        plan = _plan_reservation_batch(snapshot, materialized)
        blocked = tuple(plan.get("reservation_blocked") or ())
        if blocked:
            raise RegisteredNameReservationBatchError(blocked)
        if _try_apply_reservation_plan(hooks, plan):
            return _result_from_plan(plan)

    raise RegisteredNameReservationRetryError(
        "agent-name registry changed while applying reservation batch; retry the command"
    )


def reserve_registered_names(
    hooks: RegisteredNameRegistryBatchHooks,
    reservations: Sequence[tuple[str, str | Path]],
) -> RegisteredNameReservationBatchResult:
    """Reserve multiple planned agent names through one registry transaction."""
    return mutate_registered_name_reservations(
        hooks,
        [
            RegisteredNameReservation(
                request_id=f"reserve-planned-{index}",
                operation="reserve_planned",
                name=name,
                artifact_dir=artifact_dir,
            )
            for index, (name, artifact_dir) in enumerate(reservations)
        ],
    )


def claim_registered_names(
    hooks: RegisteredNameRegistryBatchHooks,
    reservations: Sequence[tuple[str, str | Path]],
    *,
    replace_existing: bool = False,
) -> RegisteredNameReservationBatchResult:
    """Claim multiple agent names through one registry transaction."""
    return mutate_registered_name_reservations(
        hooks,
        [
            RegisteredNameReservation(
                request_id=f"claim-planned-{index}",
                operation="claim_planned",
                name=name,
                artifact_dir=artifact_dir,
                replace_existing=replace_existing,
            )
            for index, (name, artifact_dir) in enumerate(reservations)
        ],
    )


def planned_registered_name_belongs_to_artifact(
    hooks: RegisteredNameRegistryBatchHooks,
    name: str,
    artifact_dir: str | Path,
) -> bool:
    """Return whether a raw planned reservation belongs to *artifact_dir*."""

    with hooks.mutation_lock():
        existing = _raw_equivalent_entry(hooks, name)
    return _owned_agent_entry_belongs_to_artifact(existing, artifact_dir)


def claim_exact_planned_registered_name(
    hooks: RegisteredNameRegistryBatchHooks,
    name: str,
    artifact_dir: str | Path,
) -> bool:
    """Convert a matching planned reservation to a claim without archive discovery."""

    artifact_path = Path(artifact_dir).expanduser().resolve(strict=False)
    with hooks.mutation_lock():
        data = hooks.read_registry(hooks.registry_path())
        if data is None:
            return False
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, dict):
            return False
        identity = AgentIdentitySnapshot.current()
        storage_name, existing = _raw_equivalent_entry_from_entries(
            raw_entries,
            name,
            identity,
        )
        if not _planned_entry_belongs_to_artifact(existing, artifact_path):
            return False
        entries = dict(raw_entries)
        entry = local_artifact_entry(
            hooks.mutation_operations(),
            artifact_path,
            storage_name,
            reservation_kind="claimed",
            identity=identity,
        )
        if isinstance(existing, dict) and isinstance(
            existing.get("template_namespace"), str
        ):
            entry["template_namespace"] = existing["template_namespace"]
        entries[storage_name] = entry
        hooks.save_entries_locked(entries)
        return True


def _coerce_reservation(
    item: RegisteredNameReservation | Mapping[str, Any],
) -> RegisteredNameReservation:
    if isinstance(item, RegisteredNameReservation):
        return item
    return RegisteredNameReservation(
        request_id=str(item["request_id"]),
        operation=item["operation"],
        name=str(item["name"]),
        artifact_dir=item["artifact_dir"],
        namespace=_optional_str(item.get("namespace")),
        member_name=_optional_str(item.get("member_name")),
        clan_generation=_optional_str(item.get("clan_generation")),
        create_only=bool(item.get("create_only", False)),
        replace_existing=bool(item.get("replace_existing", False)),
        allowed_existing_names=tuple(
            str(v) for v in item.get("allowed_existing_names", ())
        ),
        cleanup_token=_optional_str(item.get("cleanup_token")),
        expected_owner=(
            dict(item["expected_owner"])
            if isinstance(item.get("expected_owner"), Mapping)
            else None
        ),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _plan_reservation_batch(
    snapshot: RegisteredNameReservationSnapshot,
    reservations: Sequence[RegisteredNameReservation],
) -> dict[str, Any]:
    owner = snapshot.identity.owner
    if owner is None:
        raise RuntimeError("agent-name reservation batches require an agent owner")
    request = {
        "schema_version": agent_ownership_batch_wire_schema_version(),
        "owner": {
            "username": owner.username,
            "machine_name": owner.machine_name,
        },
        "known_owner_roots": list(snapshot.identity.known_owner_roots),
        "reservation_snapshot": [
            _entry_to_wire(name, entry) for name, entry in snapshot.entries.items()
        ],
        "reservation_requests": [item.to_wire() for item in reservations],
    }
    return plan_agent_ownership_batch(request)


def _entry_to_wire(name: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    wire = dict(entry)
    wire["name"] = name
    wire["source_owner"] = _owner_to_wire(wire.get("source_owner"))
    collision_owners = wire.get("collision_owners")
    if isinstance(collision_owners, list):
        wire["collision_owners"] = [
            _entry_to_wire(str(owner.get("name", name)), owner)
            for owner in collision_owners
            if isinstance(owner, Mapping)
        ]
    return wire


def _owner_to_wire(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine_name, str):
        return None
    return {"username": username, "machine_name": machine_name}


def _try_apply_reservation_plan(
    hooks: RegisteredNameRegistryBatchHooks,
    plan: Mapping[str, Any],
) -> bool:
    merges = [
        dict(merge)
        for merge in plan.get("registry_merge_plan") or ()
        if isinstance(merge, Mapping)
    ]
    with hooks.mutation_lock():
        path = hooks.registry_path()
        latest = hooks.read_registry(path)
        if latest is None or hooks.registry_file_is_stale(latest):
            return False
        raw_entries = latest.get("entries")
        if not isinstance(raw_entries, dict):
            return False
        if not all(_merge_predicate_matches(raw_entries, merge) for merge in merges):
            return False

        if not any(merge.get("action") in _MUTATING_MERGE_ACTIONS for merge in merges):
            return True

        entries = dict(raw_entries)
        for merge in merges:
            action = merge.get("action")
            name = merge.get("name")
            if not isinstance(name, str):
                return False
            if action == "upsert":
                entry = merge.get("entry")
                if not isinstance(entry, Mapping):
                    return False
                entries[name] = _wire_entry_to_registry(entry)
            elif action == "remove":
                entries.pop(name, None)
            elif action == "no_op":
                continue
            else:
                return False
        hooks.save_entries_locked(entries)
        return True


def _merge_predicate_matches(
    entries: Mapping[str, Any],
    merge: Mapping[str, Any],
) -> bool:
    expected = merge.get("expected")
    if not isinstance(expected, Mapping):
        return False
    name = expected.get("name")
    if not isinstance(name, str):
        return False
    existing = entries.get(name)
    if expected.get("must_be_absent") is True:
        return existing is None
    if not isinstance(existing, Mapping):
        return False
    for field in (
        "raw_suffix",
        "artifacts_dir",
        "bundle_path",
        "reservation_kind",
        "container_kind",
        "clan_generation",
    ):
        expected_value = expected.get(field)
        if expected_value is not None and existing.get(field) != expected_value:
            return False
    return True


def _wire_entry_to_registry(entry: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    out["source_owner"] = _owner_to_wire(out.get("source_owner"))
    collision_owners = out.get("collision_owners")
    if isinstance(collision_owners, list):
        out["collision_owners"] = [
            _wire_entry_to_registry(owner)
            for owner in collision_owners
            if isinstance(owner, Mapping)
        ]
    return out


def _raw_equivalent_entry(
    hooks: RegisteredNameRegistryBatchHooks,
    name: str,
) -> dict[str, Any] | None:
    data = hooks.read_registry(hooks.registry_path())
    if data is None:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    _storage_name, existing = _raw_equivalent_entry_from_entries(
        entries,
        name,
        AgentIdentitySnapshot.current(),
    )
    return existing


def _raw_equivalent_entry_from_entries(
    entries: Mapping[str, Any],
    name: str,
    identity: AgentIdentitySnapshot,
) -> tuple[str, dict[str, Any] | None]:
    for candidate in current_owner_agent_name_lookup_candidates(name, identity):
        entry = entries.get(candidate)
        if isinstance(entry, dict):
            return candidate, entry
    return name, None


def _planned_entry_belongs_to_artifact(
    entry: object,
    artifact_dir: str | Path,
) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("reservation_kind") not in _PLANNED_RESERVATION_KINDS:
        return False
    artifact_path = Path(artifact_dir).expanduser().resolve(strict=False)
    return entry_belongs_to_artifact(entry, artifact_path)


def _owned_agent_entry_belongs_to_artifact(
    entry: object,
    artifact_dir: str | Path,
) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("reservation_kind") not in _OWNED_AGENT_RESERVATION_KINDS:
        return False
    artifact_path = Path(artifact_dir).expanduser().resolve(strict=False)
    return entry_belongs_to_artifact(entry, artifact_path)


def _result_from_plan(
    plan: Mapping[str, Any],
) -> RegisteredNameReservationBatchResult:
    return RegisteredNameReservationBatchResult(
        accepted=tuple(
            dict(item)
            for item in plan.get("reservation_decisions") or ()
            if isinstance(item, Mapping)
        ),
        blocked=tuple(
            dict(item)
            for item in plan.get("reservation_blocked") or ()
            if isinstance(item, Mapping)
        ),
        registry_merge_plan=tuple(
            dict(item)
            for item in plan.get("registry_merge_plan") or ()
            if isinstance(item, Mapping)
        ),
        cleanup_reservations=tuple(
            dict(item)
            for item in plan.get("cleanup_reservations") or ()
            if isinstance(item, Mapping)
        ),
        diagnostics=tuple(str(item) for item in plan.get("diagnostics") or ()),
        raw_plan=dict(plan),
    )


def _format_blocked_reservations(
    blocked: Sequence[Mapping[str, Any]],
) -> str:
    details = []
    for item in blocked:
        request_id = item.get("request_id")
        detail = item.get("detail") or item.get("reason") or "blocked"
        if request_id:
            details.append(f"{request_id}: {detail}")
        else:
            details.append(str(detail))
    return "registry reservation batch blocked: " + "; ".join(details)


__all__ = [
    "RegisteredNameReservation",
    "RegisteredNameReservationBatchError",
    "RegisteredNameReservationBatchResult",
    "RegisteredNameReservationRetryError",
    "RegisteredNameReservationSnapshot",
    "RegisteredNameRegistryBatchHooks",
    "RegistryReservationOperation",
    "claim_exact_planned_registered_name",
    "claim_registered_names",
    "mutate_registered_name_reservations",
    "planned_registered_name_belongs_to_artifact",
    "registered_name_reservation_snapshot",
    "reserve_registered_names",
]
