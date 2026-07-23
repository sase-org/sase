"""Mutation operations for the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol

from sase.agent.names._registry_entries import (
    imported_v2_entry_provenance,
    imported_v1_entry_provenance,
    local_entry_provenance,
    owner_namespace_entry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    AgentOwnershipClassification,
    AgentSourceOwnerIdentity,
    classify_imported_agent_owner,
    current_owner_agent_name_key,
    current_owner_agent_name_lookup_candidates,
    localize_imported_agent_name,
    normalize_owned_agent_name,
    present_agent_name,
)


class _OwnerEntryFactory(Protocol):
    def __call__(
        self,
        artifact_dir: Path,
        name: str,
        *,
        reservation_kind: str,
        template_namespace: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RegistryMutationOperations:
    """Registry callbacks used by mutations while preserving facade test seams."""

    lock: Callable[[], AbstractContextManager[None]]
    load: Callable[[], dict[str, Any]]
    save_entries: Callable[[dict[str, Any]], None]
    owner_from_artifact_name: _OwnerEntryFactory
    entry_belongs_to_artifact: Callable[[dict[str, Any], Path], bool]
    entry_has_other_owner: Callable[[dict[str, Any], Path], bool]
    dotted_namespace_prefixes: Callable[[str], set[str]]
    equivalent_entry: Callable[
        [Mapping[str, Any], str, AgentIdentitySnapshot],
        tuple[str, dict[str, Any] | None],
    ]
    raise_name_collision: Callable[[str], NoReturn]
    raise_container_name_collision: Callable[[str, dict[str, Any]], NoReturn]
    lowest_name_suggestion: Callable[[str], str]


def claim_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    claiming_dir: str | Path,
    *,
    replace_existing: bool = False,
) -> None:
    """Best-effort upsert of a claimed name into the registry."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        _ensure_local_namespace_available(entries, name)
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict) and existing.get("container_kind"):
            operations.raise_container_name_collision(name, existing)
        if isinstance(existing, dict) and operations.entry_has_other_owner(
            existing, artifact_dir
        ):
            if not replace_existing or storage_name != name:
                from sase.agent.names._common import NameCollisionError

                visible_name = present_agent_name(name, identity)
                suggestion = operations.lowest_name_suggestion(visible_name)
                raise NameCollisionError(
                    f"agent name '{visible_name}' is already taken; try '{suggestion}'"
                )
        entry = _local_artifact_entry(
            operations,
            artifact_dir,
            storage_name,
            reservation_kind="claimed",
            identity=identity,
        )
        entries[storage_name] = entry
        operations.save_entries(entries)


def claim_imported_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    source_machine: str,
    claiming_dir: str | Path,
    *,
    digest: str,
) -> None:
    """Claim an exact foreign machine-qualified imported agent name.

    Imported names deliberately bypass local qualification: a previously
    unknown hood such as ``zeus.worker`` must remain exactly that spelling,
    rather than becoming ``<local>.zeus.worker``. The source machine must
    match the durable prefix, and only the same imported owner may refresh its
    digest.
    """
    from sase.agents_sync.io import validate_machine, validate_qualified_name

    source_machine = validate_machine(source_machine)
    name = validate_qualified_name(name, source_machine)
    artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
    with operations.lock():
        entries = dict(operations.load()["entries"])
        existing = entries.get(name)
        if isinstance(existing, dict):
            same_import = (
                existing.get("reservation_kind") == "imported"
                and existing.get("imported_from_machine") == source_machine
                and operations.entry_belongs_to_artifact(existing, artifact_dir)
            )
            if not same_import:
                from sase.agent.names._common import ImportedNameCollisionError

                raise ImportedNameCollisionError(
                    name,
                    reason="the destination is already reserved by another owner",
                    existing=existing,
                )
        _ensure_import_namespace_available(
            entries,
            source_root=source_machine,
            source_owner=None,
            destination_name=name,
        )
        entry = operations.owner_from_artifact_name(
            artifact_dir,
            name,
            reservation_kind="imported",
        )
        entry.update(imported_v1_entry_provenance(source_machine, digest))
        entries.setdefault(
            source_machine,
            owner_namespace_entry(
                source_machine,
                namespace_kind="legacy_source_machine",
            ),
        )
        entries[name] = entry
        operations.save_entries(entries)


def claim_imported_registered_name_v2(
    operations: RegistryMutationOperations,
    source_owner: AgentOwnerIdentity,
    canonical_global_name: str,
    localized_name: str,
    claiming_dir: str | Path,
    *,
    digest: str,
) -> None:
    """Atomically claim one explicitly owned v2 import.

    The caller supplies both global and localized spellings so the registry can
    validate the boundary instead of deriving provenance from dotted text.
    """
    identity = AgentIdentitySnapshot.current()
    source = AgentSourceOwnerIdentity.v2(source_owner)
    expected_name = localize_imported_agent_name(
        canonical_global_name,
        source,
        identity,
    )
    if expected_name != localized_name:
        raise ValueError(
            "localized imported name does not match explicit source ownership: "
            f"expected '{expected_name}', got '{localized_name}'"
        )

    artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
    classification = classify_imported_agent_owner(source, identity)
    source_root: str | None
    if classification is AgentOwnershipClassification.EXACT_OWNER:
        source_root = None
        candidates = current_owner_agent_name_lookup_candidates(
            localized_name,
            identity,
        )
    elif classification is AgentOwnershipClassification.SAME_USER_OTHER_MACHINE:
        source_root = source_owner.machine_name
        candidates = (localized_name,)
    else:
        source_root = source_owner.username
        candidates = (localized_name,)

    with operations.lock():
        entries = dict(operations.load()["entries"])
        existing_name: str | None = None
        existing: dict[str, Any] | None = None
        for candidate in candidates:
            value = entries.get(candidate)
            if isinstance(value, dict):
                existing_name = candidate
                existing = value
                break
        if existing is not None:
            exact_local_refresh = (
                classification is AgentOwnershipClassification.EXACT_OWNER
                and existing.get("origin") == "local"
                and existing.get("canonical_global_name") == canonical_global_name
                and operations.entry_belongs_to_artifact(existing, artifact_dir)
            )
            same_claim = (
                existing.get("origin") == "import_v2"
                and existing.get("canonical_global_name") == canonical_global_name
                and _entry_source_owner(existing) == source_owner
                and operations.entry_belongs_to_artifact(existing, artifact_dir)
            )
            if exact_local_refresh:
                return
            if not same_claim:
                from sase.agent.names._common import ImportedNameCollisionError

                raise ImportedNameCollisionError(
                    localized_name,
                    reason=(
                        "owner, global identity, or artifact owner differs from "
                        "the existing claim"
                    ),
                    existing=existing,
                )
        if source_root is not None:
            _ensure_import_namespace_available(
                entries,
                source_root=source_root,
                source_owner=source_owner,
                destination_name=localized_name,
            )

        entry = operations.owner_from_artifact_name(
            artifact_dir,
            localized_name,
            reservation_kind="imported",
        )
        entry.update(
            imported_v2_entry_provenance(
                source_owner,
                canonical_global_name,
                digest,
            )
        )
        if existing_name is not None and existing_name != localized_name:
            entries.pop(existing_name, None)
        if source_root is not None:
            namespace_kind = (
                "sibling_machine"
                if classification
                is AgentOwnershipClassification.SAME_USER_OTHER_MACHINE
                else "foreign_username"
            )
            existing_root = entries.get(source_root)
            if not isinstance(existing_root, dict) or (
                existing_root.get("container_kind") == "owner_namespace"
                and existing_root.get("source_owner") is None
            ):
                entries[source_root] = owner_namespace_entry(
                    source_root,
                    namespace_kind=namespace_kind,
                    source_owner=source_owner,
                )
        entries[localized_name] = entry
        operations.save_entries(entries)


def reserve_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    claiming_dir: str | Path,
) -> None:
    """Reserve *name* for a not-yet-started agent artifacts directory."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        _ensure_local_namespace_available(entries, name)
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict) and existing.get("container_kind"):
            operations.raise_container_name_collision(name, existing)
        if isinstance(existing, dict) and operations.entry_has_other_owner(
            existing, artifact_dir
        ):
            from sase.agent.names._common import NameCollisionError

            visible_name = present_agent_name(name, identity)
            suggestion = operations.lowest_name_suggestion(visible_name)
            raise NameCollisionError(
                f"agent name '{visible_name}' is already taken; try '{suggestion}'"
            )
        entry = _local_artifact_entry(
            operations,
            artifact_dir,
            storage_name,
            reservation_kind="planned",
            identity=identity,
        )
        entries[storage_name] = entry
        operations.save_entries(entries)


def reserve_registered_clan_name(
    operations: RegistryMutationOperations,
    name: str,
    generation: str,
    claiming_dir: str | Path,
    *,
    create_only: bool = False,
) -> str:
    """Reserve a clan and return its allocation-locked generation."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        _ensure_local_namespace_available(entries, name)
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") == "clan":
                if create_only:
                    from sase.agent.names._common import NameCollisionError

                    visible_name = present_agent_name(name, identity)
                    raise NameCollisionError(
                        f"clan '{visible_name}' already exists; join it with "
                        f"%id(<id>, clan={visible_name})"
                    )
                existing_generation = existing.get("clan_generation")
                return (
                    existing_generation
                    if isinstance(existing_generation, str) and existing_generation
                    else generation
                )
            from sase.agent.names._common import NameCollisionError

            visible_name = present_agent_name(name, identity)
            raise NameCollisionError(
                f"clan name '{visible_name}' is already reserved by an agent; "
                "choose a different clan name"
            )
        entry = _local_artifact_entry(
            operations,
            artifact_dir,
            storage_name,
            reservation_kind="planned_clan",
            identity=identity,
        )
        entry["container_kind"] = "clan"
        entry["clan_generation"] = generation
        entries[storage_name] = entry
        operations.save_entries(entries)
        return generation


def claim_registered_clan_name(
    operations: RegistryMutationOperations,
    name: str,
    generation: str,
    claiming_dir: str | Path,
) -> None:
    """Persist a clan container after one of its members publishes metadata."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        _ensure_local_namespace_available(entries, name)
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") != "clan":
                from sase.agent.names._common import NameCollisionError

                visible_name = present_agent_name(name, identity)
                raise NameCollisionError(
                    f"clan name '{visible_name}' is already reserved by an agent; "
                    "choose a different clan name"
                )
            if existing.get(
                "reservation_kind"
            ) != "planned_clan" and not operations.entry_belongs_to_artifact(
                existing, artifact_dir
            ):
                return
        entry = _local_artifact_entry(
            operations,
            artifact_dir,
            storage_name,
            reservation_kind="clan",
            identity=identity,
        )
        entry["container_kind"] = "clan"
        entry["clan_generation"] = generation
        entries[storage_name] = entry
        operations.save_entries(entries)


def convert_registered_agent_to_family(
    operations: RegistryMutationOperations,
    name: str,
    member_name: str,
    claiming_dir: str | Path,
) -> None:
    """Convert one agent claim into a family container plus member claim."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        member_name = normalize_owned_agent_name(member_name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        _ensure_local_namespace_available(entries, name)
        _ensure_local_namespace_available(entries, member_name)
        family_storage_name, existing = operations.equivalent_entry(
            entries, name, identity
        )
        if isinstance(existing, dict):
            container_kind = existing.get("container_kind")
            if container_kind == "clan":
                operations.raise_container_name_collision(name, existing)
            if container_kind not in {None, "family"}:
                operations.raise_container_name_collision(name, existing)
            if container_kind is None and operations.entry_has_other_owner(
                existing, artifact_dir
            ):
                operations.raise_name_collision(name)

        member_storage_name, member_existing = operations.equivalent_entry(
            entries, member_name, identity
        )
        if isinstance(member_existing, dict) and operations.entry_has_other_owner(
            member_existing, artifact_dir
        ):
            operations.raise_name_collision(member_name)

        family_entry = _local_artifact_entry(
            operations,
            artifact_dir,
            family_storage_name,
            reservation_kind="family",
            identity=identity,
        )
        family_entry["container_kind"] = "family"
        entries[family_storage_name] = family_entry
        entries[member_storage_name] = _local_artifact_entry(
            operations,
            artifact_dir,
            member_storage_name,
            reservation_kind="claimed",
            identity=identity,
        )
        operations.save_entries(entries)


def release_planned_registered_clan_name(
    operations: RegistryMutationOperations,
    name: str,
    generation: str,
    claiming_dir: str | Path,
) -> None:
    """Release a clan reservation when no member in its batch spawned."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if not isinstance(existing, dict):
            return
        if existing.get("reservation_kind") != "planned_clan":
            return
        if existing.get("clan_generation") != generation:
            return
        if not operations.entry_belongs_to_artifact(existing, artifact_dir):
            return
        entries.pop(storage_name, None)
        operations.save_entries(entries)


def reserve_registered_template_name(
    operations: RegistryMutationOperations,
    name: str,
    namespace: str,
    claiming_dir: str | Path,
    *,
    allowed_existing_names: Collection[str] = (),
) -> None:
    """Reserve a template-allocated *name* after checking *namespace*."""
    reserve_registered_template_names(
        operations,
        [(name, namespace, claiming_dir)],
        allowed_existing_names=allowed_existing_names,
    )


def reserve_registered_template_names(
    operations: RegistryMutationOperations,
    reservations: Sequence[tuple[str, str, str | Path]],
    *,
    allowed_existing_names: Collection[str] = (),
) -> None:
    """Reserve template-allocated names atomically with namespace checks."""
    if not reservations:
        return

    identity = AgentIdentitySnapshot.current()
    materialized_reservations = [
        (
            normalize_owned_agent_name(name, identity),
            normalize_owned_agent_name(namespace, identity),
            claiming_dir,
        )
        for name, namespace, claiming_dir in reservations
    ]
    names = [name for name, _, _ in materialized_reservations]
    name_keys = [current_owner_agent_name_key(name, identity) for name in names]
    if len(set(name_keys)) != len(name_keys):
        from sase.agent.names._common import NameCollisionError

        raise NameCollisionError(
            "template allocation group rendered duplicate concrete names"
        )

    allowed = {
        current_owner_agent_name_key(name, identity) for name in allowed_existing_names
    }
    with operations.lock():
        entries = dict(operations.load()["entries"])
        occupied_namespaces = {
            prefix
            for existing_name, existing_entry in entries.items()
            if not (
                isinstance(existing_entry, dict)
                and existing_entry.get("container_kind") == "clan"
            )
            if current_owner_agent_name_key(existing_name, identity) not in allowed
            for prefix in operations.dotted_namespace_prefixes(
                current_owner_agent_name_key(existing_name, identity)
            )
        }
        materialized = [
            (
                name,
                namespace,
                Path(claiming_dir).expanduser().resolve(strict=False),
            )
            for name, namespace, claiming_dir in materialized_reservations
        ]
        for name, namespace, artifact_dir in materialized:
            _ensure_local_namespace_available(entries, name)
            _ensure_local_namespace_available(entries, namespace)
            _storage_name, existing = operations.equivalent_entry(
                entries, name, identity
            )
            if isinstance(existing, dict) and operations.entry_has_other_owner(
                existing, artifact_dir
            ):
                operations.raise_name_collision(name)
            if current_owner_agent_name_key(namespace, identity) in occupied_namespaces:
                operations.raise_name_collision(name)

        for name, namespace, artifact_dir in materialized:
            storage_name, _existing = operations.equivalent_entry(
                entries, name, identity
            )
            entry = _local_artifact_entry(
                operations,
                artifact_dir,
                storage_name,
                reservation_kind="planned",
                template_namespace=namespace,
                identity=identity,
            )
            entries[storage_name] = entry
        operations.save_entries(entries)


def release_planned_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    claiming_dir: str | Path,
) -> None:
    """Remove a still-planned reservation for *name* owned by *claiming_dir*."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if not isinstance(existing, dict):
            return
        if existing.get("reservation_kind") != "planned":
            return
        if not operations.entry_belongs_to_artifact(existing, artifact_dir):
            return
        entries.pop(storage_name, None)
        operations.save_entries(entries)


def delete_registered_name(
    operations: RegistryMutationOperations,
    name: str,
) -> None:
    """Remove *name* from the registry."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        entries = operations.load()["entries"]
        from sase.core.agent_identity_facade import (
            current_owner_agent_name_lookup_candidates,
        )

        candidates = current_owner_agent_name_lookup_candidates(name, identity)
        if not any(candidate in entries for candidate in candidates):
            return
        entries = dict(entries)
        for candidate in candidates:
            entries.pop(candidate, None)
        operations.save_entries(entries)


def _local_artifact_entry(
    operations: RegistryMutationOperations,
    artifact_dir: Path,
    name: str,
    *,
    reservation_kind: str,
    identity: AgentIdentitySnapshot,
    template_namespace: str | None = None,
) -> dict[str, Any]:
    entry = operations.owner_from_artifact_name(
        artifact_dir,
        name,
        reservation_kind=reservation_kind,
        template_namespace=template_namespace,
    )
    entry.update(local_entry_provenance(name, identity))
    return entry


def _entry_source_owner(entry: Mapping[str, Any]) -> AgentOwnerIdentity | None:
    value = entry.get("source_owner")
    if not isinstance(value, Mapping):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine_name, str):
        return None
    return AgentOwnerIdentity(username, machine_name)


def _ensure_import_namespace_available(
    entries: Mapping[str, Any],
    *,
    source_root: str,
    source_owner: AgentOwnerIdentity | None,
    destination_name: str,
) -> None:
    """Reject a foreign hood if any existing spelling belongs elsewhere."""
    from sase.agent.names._common import ImportedNameCollisionError

    for stored_name, raw_entry in entries.items():
        if stored_name != source_root and not stored_name.startswith(f"{source_root}."):
            continue
        if not isinstance(raw_entry, dict):
            raise ImportedNameCollisionError(
                destination_name,
                reason=f"owner namespace '{source_root}' contains invalid state",
            )
        if raw_entry.get("container_kind") == "owner_namespace":
            existing_owner = _entry_source_owner(raw_entry)
            if existing_owner == source_owner:
                continue
            if (
                existing_owner is None
                and raw_entry.get("namespace_kind") == "sibling_machine"
                and (source_owner is None or source_owner.machine_name == source_root)
            ):
                continue
            if source_owner is None and raw_entry.get("namespace_kind") in {
                "legacy_source_machine",
                "sibling_machine",
            }:
                continue
        elif (
            source_owner is not None and _entry_source_owner(raw_entry) == source_owner
        ):
            continue
        elif source_owner is None and (
            raw_entry.get("origin") == "import_v1"
            and raw_entry.get("legacy_source_machine") == source_root
        ):
            continue
        raise ImportedNameCollisionError(
            destination_name,
            reason=f"owner namespace '{source_root}' is already occupied",
            existing=raw_entry,
        )


def _ensure_local_namespace_available(
    entries: Mapping[str, Any],
    name: str,
) -> None:
    """Prevent local allocation beneath reserved foreign owner roots."""
    from sase.agent.names._common import NameCollisionError

    parts = name.split(".")
    for index in range(1, len(parts) + 1):
        prefix = ".".join(parts[:index])
        entry = entries.get(prefix)
        if not isinstance(entry, dict):
            continue
        if entry.get("container_kind") != "owner_namespace" and entry.get(
            "origin"
        ) not in {"import_v1", "import_v2"}:
            continue
        raise NameCollisionError(
            f"agent name '{name}' is inside reserved owner namespace '{prefix}'"
        )
