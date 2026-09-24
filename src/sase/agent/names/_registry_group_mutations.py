"""Registry mutations for clan and agent-session containers."""

from __future__ import annotations

from pathlib import Path

from sase.agent.names._registry_entries import AGENT_SESSION_CONTAINER_KIND
from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations,
    ensure_local_namespace_available,
    local_artifact_entry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    normalize_owned_agent_name,
    present_agent_name,
)


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
        ensure_local_namespace_available(entries, name)
        storage_name, existing = operations.equivalent_entry(entries, name, identity)
        if isinstance(existing, dict):
            if existing.get("container_kind") == "clan":
                existing_generation = existing.get("clan_generation")
                if (
                    existing.get("reservation_kind") == "planned_clan"
                    and existing_generation == generation
                    and operations.entry_belongs_to_artifact(existing, artifact_dir)
                ):
                    return generation
                if create_only:
                    from sase.agent.names._common import NameCollisionError

                    visible_name = present_agent_name(name, identity)
                    raise NameCollisionError(
                        f"clan '{visible_name}' already exists; join it with "
                        f"%id(<id>, clan={visible_name})"
                    )
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
        entry = local_artifact_entry(
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
        ensure_local_namespace_available(entries, name)
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
        entry = local_artifact_entry(
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


def convert_registered_agent_to_agent_session(
    operations: RegistryMutationOperations,
    name: str,
    member_name: str,
    claiming_dir: str | Path,
) -> None:
    """Convert one agent claim into a session container plus member claim."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = normalize_owned_agent_name(name, identity)
        member_name = normalize_owned_agent_name(member_name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        ensure_local_namespace_available(entries, name)
        ensure_local_namespace_available(entries, member_name)
        agent_session_storage_name, existing = operations.equivalent_entry(
            entries, name, identity
        )
        if isinstance(existing, dict):
            container_kind = existing.get("container_kind")
            if container_kind == "clan":
                operations.raise_container_name_collision(name, existing)
            # legacy agent-family spelling: a stored "family" container converts too.
            if container_kind not in {
                None,
                AGENT_SESSION_CONTAINER_KIND,
                "family",
            }:
                operations.raise_container_name_collision(name, existing)
            if container_kind is None and operations.entry_has_other_claim_owner(
                existing, artifact_dir
            ):
                operations.raise_name_collision(name)

        member_storage_name, member_existing = operations.equivalent_entry(
            entries, member_name, identity
        )
        if isinstance(member_existing, dict) and operations.entry_has_other_claim_owner(
            member_existing, artifact_dir
        ):
            operations.raise_name_collision(member_name)

        agent_session_entry = local_artifact_entry(
            operations,
            artifact_dir,
            agent_session_storage_name,
            reservation_kind=AGENT_SESSION_CONTAINER_KIND,
            identity=identity,
        )
        agent_session_entry["container_kind"] = AGENT_SESSION_CONTAINER_KIND
        entries[agent_session_storage_name] = agent_session_entry
        entries[member_storage_name] = local_artifact_entry(
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
