"""Mutation operations for the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol

from sase.core.machine_hood_facade import (
    MachineHoodIdentity,
    canonical_local_agent_name_key,
    local_agent_name_lookup_candidates,
    qualify_local_agent_name,
    strip_local_agent_name,
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
        [Mapping[str, Any], str, MachineHoodIdentity],
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict) and existing.get("container_kind"):
            operations.raise_container_name_collision(name, existing)
        if isinstance(existing, dict) and not replace_existing:
            if operations.entry_has_other_owner(existing, artifact_dir):
                from sase.agent.names._common import NameCollisionError

                visible_name = strip_local_agent_name(name, identity)
                suggestion = operations.lowest_name_suggestion(visible_name)
                raise NameCollisionError(
                    f"agent name '{visible_name}' is already taken; try '{suggestion}'"
                )
        entry = operations.owner_from_artifact_name(
            artifact_dir, storage_name, reservation_kind="claimed"
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
                from sase.agent.names._common import NameCollisionError

                raise NameCollisionError(
                    f"imported agent name '{name}' is already reserved"
                )
        entry = operations.owner_from_artifact_name(
            artifact_dir,
            name,
            reservation_kind="imported",
        )
        entry["imported_from_machine"] = source_machine
        entry["imported_digest"] = digest
        entries[name] = entry
        operations.save_entries(entries)


def reserve_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    claiming_dir: str | Path,
) -> None:
    """Reserve *name* for a not-yet-started agent artifacts directory."""
    with operations.lock():
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict) and existing.get("container_kind"):
            operations.raise_container_name_collision(name, existing)
        if isinstance(existing, dict) and operations.entry_has_other_owner(
            existing, artifact_dir
        ):
            from sase.agent.names._common import NameCollisionError

            visible_name = strip_local_agent_name(name, identity)
            suggestion = operations.lowest_name_suggestion(visible_name)
            raise NameCollisionError(
                f"agent name '{visible_name}' is already taken; try '{suggestion}'"
            )
        entry = operations.owner_from_artifact_name(
            artifact_dir, storage_name, reservation_kind="planned"
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") == "clan":
                if create_only:
                    from sase.agent.names._common import NameCollisionError

                    visible_name = strip_local_agent_name(name, identity)
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

            visible_name = strip_local_agent_name(name, identity)
            raise NameCollisionError(
                f"clan name '{visible_name}' is already reserved by an agent; "
                "choose a different clan name"
            )
        entry = operations.owner_from_artifact_name(
            artifact_dir,
            storage_name,
            reservation_kind="planned_clan",
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") != "clan":
                from sase.agent.names._common import NameCollisionError

                visible_name = strip_local_agent_name(name, identity)
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
        entry = operations.owner_from_artifact_name(
            artifact_dir,
            storage_name,
            reservation_kind="clan",
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
        member_name = qualify_local_agent_name(member_name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
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

        family_entry = operations.owner_from_artifact_name(
            artifact_dir,
            family_storage_name,
            reservation_kind="family",
        )
        family_entry["container_kind"] = "family"
        entries[family_storage_name] = family_entry
        entries[member_storage_name] = operations.owner_from_artifact_name(
            artifact_dir,
            member_storage_name,
            reservation_kind="claimed",
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
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

    identity = MachineHoodIdentity.current()
    materialized_reservations = [
        (
            qualify_local_agent_name(name, identity),
            qualify_local_agent_name(namespace, identity),
            claiming_dir,
        )
        for name, namespace, claiming_dir in reservations
    ]
    names = [name for name, _, _ in materialized_reservations]
    name_keys = [canonical_local_agent_name_key(name, identity) for name in names]
    if len(set(name_keys)) != len(name_keys):
        from sase.agent.names._common import NameCollisionError

        raise NameCollisionError(
            "template allocation group rendered duplicate concrete names"
        )

    allowed = {
        canonical_local_agent_name_key(name, identity)
        for name in allowed_existing_names
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
            if canonical_local_agent_name_key(existing_name, identity) not in allowed
            for prefix in operations.dotted_namespace_prefixes(
                canonical_local_agent_name_key(existing_name, identity)
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
            _storage_name, existing = operations.equivalent_entry(
                entries, name, identity
            )
            if isinstance(existing, dict) and operations.entry_has_other_owner(
                existing, artifact_dir
            ):
                operations.raise_name_collision(name)
            if (
                canonical_local_agent_name_key(namespace, identity)
                in occupied_namespaces
            ):
                operations.raise_name_collision(name)

        for name, namespace, artifact_dir in materialized:
            storage_name, _existing = operations.equivalent_entry(
                entries, name, identity
            )
            entry = operations.owner_from_artifact_name(
                artifact_dir,
                storage_name,
                reservation_kind="planned",
                template_namespace=namespace,
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
        identity = MachineHoodIdentity.current()
        name = qualify_local_agent_name(name, identity)
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
        identity = MachineHoodIdentity.current()
        entries = operations.load()["entries"]
        candidates = local_agent_name_lookup_candidates(name, identity)
        if not any(candidate in entries for candidate in candidates):
            return
        entries = dict(entries)
        for candidate in candidates:
            entries.pop(candidate, None)
        operations.save_entries(entries)
