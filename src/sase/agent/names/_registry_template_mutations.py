"""Registry mutations for template-allocated agent names."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path

from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations,
    ensure_local_namespace_available,
    local_artifact_entry,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    current_owner_agent_name_key,
    normalize_owned_agent_name,
)


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
            ensure_local_namespace_available(entries, name)
            ensure_local_namespace_available(entries, namespace)
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
            entry = local_artifact_entry(
                operations,
                artifact_dir,
                storage_name,
                reservation_kind="planned",
                template_namespace=namespace,
                identity=identity,
            )
            entries[storage_name] = entry
        operations.save_entries(entries)
