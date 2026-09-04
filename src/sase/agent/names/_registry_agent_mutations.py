"""Registry mutations for individual local agent names."""

from __future__ import annotations

from pathlib import Path

from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations,
    ensure_local_namespace_available,
    local_artifact_entry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    current_owner_agent_name_lookup_candidates,
    foreign_agent_owner_root,
    normalize_owned_agent_name,
    present_agent_name,
)


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
        name = _normalize_local_registry_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        ensure_local_namespace_available(entries, name)
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
        entry = local_artifact_entry(
            operations,
            artifact_dir,
            storage_name,
            reservation_kind="claimed",
            identity=identity,
        )
        entries[storage_name] = entry
        operations.save_entries(entries)


def reserve_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    claiming_dir: str | Path,
) -> None:
    """Reserve *name* for a not-yet-started agent artifacts directory."""
    with operations.lock():
        identity = AgentIdentitySnapshot.current()
        name = _normalize_local_registry_name(name, identity)
        artifact_dir = Path(claiming_dir).expanduser().resolve(strict=False)
        entries = dict(operations.load()["entries"])
        ensure_local_namespace_available(entries, name)
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
        entry = local_artifact_entry(
            operations,
            artifact_dir,
            storage_name,
            reservation_kind="planned",
            identity=identity,
        )
        entries[storage_name] = entry
        operations.save_entries(entries)


def _normalize_local_registry_name(
    name: str,
    identity: AgentIdentitySnapshot,
) -> str:
    try:
        return normalize_owned_agent_name(name, identity)
    except ValueError as exc:
        foreign_root = foreign_agent_owner_root(name, identity)
        if foreign_root is None:
            raise
        from sase.agent.names._common import NameCollisionError

        raise NameCollisionError(
            f"agent name '{name}' is inside reserved owner namespace '{foreign_root}'"
        ) from exc


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
        candidates = current_owner_agent_name_lookup_candidates(name, identity)
        if not any(candidate in entries for candidate in candidates):
            return
        entries = dict(entries)
        for candidate in candidates:
            entries.pop(candidate, None)
        operations.save_entries(entries)
