"""Public mutation facade for the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from sase.agent.names import _registry_mutations
from sase.agent.names._registry_mutation_support import RegistryMutationOperations

_MutationOperationsFactory = Callable[[], RegistryMutationOperations]


class _RegistryMutationFacade:
    def __init__(self, mutation_operations: _MutationOperationsFactory) -> None:
        self._mutation_operations = mutation_operations

    def claim_registered_name(
        self,
        name: str,
        claiming_dir: str | Path,
        *,
        replace_existing: bool = False,
    ) -> None:
        """Best-effort upsert of a claimed name into the registry."""
        _registry_mutations.claim_registered_name(
            self._mutation_operations(),
            name,
            claiming_dir,
            replace_existing=replace_existing,
        )

    def reserve_registered_name(self, name: str, claiming_dir: str | Path) -> None:
        """Reserve *name* for a not-yet-started agent artifacts directory.

        Planned launch reservations are intentionally collision-checked like
        explicit claims, but they use ``reservation_kind="planned"`` so callers can
        roll them back if the child process never starts. The child runner's later
        regular claim is idempotent because it uses the same artifacts owner.
        """
        _registry_mutations.reserve_registered_name(
            self._mutation_operations(), name, claiming_dir
        )

    def reserve_registered_clan_name(
        self,
        name: str,
        generation: str,
        claiming_dir: str | Path,
        *,
        create_only: bool = False,
    ) -> str:
        """Reserve a clan and return its allocation-locked generation.

        ``create_only`` makes an existing clan a collision. The check and new
        reservation happen under the same allocation lock so concurrent clan
        declarations cannot both succeed.
        """
        return _registry_mutations.reserve_registered_clan_name(
            self._mutation_operations(),
            name,
            generation,
            claiming_dir,
            create_only=create_only,
        )

    def claim_registered_clan_name(
        self,
        name: str,
        generation: str,
        claiming_dir: str | Path,
    ) -> None:
        """Persist a clan container after one of its members publishes metadata."""
        _registry_mutations.claim_registered_clan_name(
            self._mutation_operations(), name, generation, claiming_dir
        )

    def convert_registered_agent_to_family(
        self,
        name: str,
        member_name: str,
        claiming_dir: str | Path,
    ) -> None:
        """Convert one agent claim into a family container plus member claim."""
        _registry_mutations.convert_registered_agent_to_family(
            self._mutation_operations(), name, member_name, claiming_dir
        )

    def release_planned_registered_clan_name(
        self,
        name: str,
        generation: str,
        claiming_dir: str | Path,
    ) -> None:
        """Release a clan reservation when no member in its batch spawned."""
        _registry_mutations.release_planned_registered_clan_name(
            self._mutation_operations(), name, generation, claiming_dir
        )

    def reserve_registered_template_name(
        self,
        name: str,
        namespace: str,
        claiming_dir: str | Path,
        *,
        allowed_existing_names: Collection[str] = (),
    ) -> None:
        """Reserve a template-allocated *name* after checking *namespace*."""
        _registry_mutations.reserve_registered_template_name(
            self._mutation_operations(),
            name,
            namespace,
            claiming_dir,
            allowed_existing_names=allowed_existing_names,
        )

    def reserve_registered_template_names(
        self,
        reservations: Sequence[tuple[str, str, str | Path]],
        *,
        allowed_existing_names: Collection[str] = (),
    ) -> None:
        """Reserve template-allocated names atomically with namespace checks.

        Names in the same batch may share a namespace, but an existing registry
        entry blocks a namespace when it is exactly that namespace or a dotted
        descendant of it. ``allowed_existing_names`` lets one parent-side template
        group add later siblings beneath namespaces it already reserved.
        """
        _registry_mutations.reserve_registered_template_names(
            self._mutation_operations(),
            reservations,
            allowed_existing_names=allowed_existing_names,
        )

    def release_planned_registered_name(
        self,
        name: str,
        claiming_dir: str | Path,
    ) -> None:
        """Remove a still-planned reservation for *name* owned by *claiming_dir*."""
        _registry_mutations.release_planned_registered_name(
            self._mutation_operations(), name, claiming_dir
        )

    def delete_registered_name(self, name: str) -> None:
        """Remove *name* from the registry."""
        _registry_mutations.delete_registered_name(self._mutation_operations(), name)


def bind_registry_mutations(
    mutation_operations: _MutationOperationsFactory,
) -> _RegistryMutationFacade:
    """Bind registry mutation functions to runtime operations."""
    return _RegistryMutationFacade(mutation_operations)
