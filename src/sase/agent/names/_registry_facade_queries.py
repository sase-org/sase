"""Public query facade for the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.agent.names import _registry_queries

_RegistryLoader = Callable[[], dict[str, Any]]


class _RegistryQueryFacade:
    def __init__(
        self,
        *,
        reservation_loader: _RegistryLoader,
        display_loader: _RegistryLoader,
    ) -> None:
        self._reservation_loader = reservation_loader
        self._display_loader = display_loader

    def lookup_registered_name(self, name: str) -> dict[str, Any] | None:
        """Return registry owner metadata for *name*, if reserved."""
        return _registry_queries.lookup_registered_name(
            name, load_registry=self._reservation_loader
        )

    def is_name_reserved(self, name: str) -> bool:
        """Return whether *name* is reserved by an existing agent."""
        return _registry_queries.is_name_reserved(
            name, load_registry=self._reservation_loader
        )

    def get_reserved_agent_names(self) -> set[str]:
        """Return every name currently reserved by the registry."""
        return _registry_queries.get_reserved_agent_names(
            load_registry=self._reservation_loader
        )

    def get_reserved_clan_names(self) -> set[str]:
        """Return every name owned by a clan container."""
        return _registry_queries.get_reserved_clan_names(
            load_registry=self._reservation_loader
        )

    def get_reserved_family_names(self) -> set[str]:
        """Return every name owned by a sequential family container."""
        return _registry_queries.get_reserved_family_names(
            load_registry=self._reservation_loader
        )

    def get_blocked_local_namespace_roots(self) -> dict[str, dict[str, Any]]:
        """Return ``{root_name: entry}`` for registry entries blocking allocation."""
        return _registry_queries.get_blocked_local_namespace_roots(
            load_registry=self._reservation_loader
        )

    def get_reserved_family_names_for_display(self) -> set[str]:
        """Return family-container names for a render, never forcing a rebuild.

        Link rendering only needs to know which names are family containers so it
        can shape a URL. Unlike :func:`get_reserved_family_names`, which gates
        allocation and must pay the full staleness proof, this read tolerates a
        stale answer rather than take the name-allocation lock.
        """
        return _registry_queries.get_reserved_family_names(
            load_registry=self._display_loader
        )

    def get_reserved_agent_name_map(self) -> dict[str, str]:
        """Return ``{name: owner_path}`` for registered names with a known owner."""
        return _registry_queries.get_reserved_agent_name_map(
            load_registry=self._reservation_loader
        )

    def lowest_name_suggestion(self, base: str) -> str:
        """Return the lowest available ``<base><N>`` suggestion."""
        return _registry_queries.lowest_name_suggestion(
            base, load_registry=self._reservation_loader
        )


def bind_registry_queries(
    *,
    reservation_loader: _RegistryLoader,
    display_loader: _RegistryLoader,
) -> _RegistryQueryFacade:
    """Bind registry query functions to runtime loaders."""
    return _RegistryQueryFacade(
        reservation_loader=reservation_loader,
        display_loader=display_loader,
    )
