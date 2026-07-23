"""Read-only projections over the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.core.machine_hood_facade import (
    MachineHoodIdentity,
    canonical_local_agent_name_key,
    local_agent_name_lookup_candidates,
    strip_local_agent_name,
)

RegistryLoader = Callable[[], dict[str, Any]]


def lookup_registered_name(
    name: str, *, load_registry: RegistryLoader
) -> dict[str, Any] | None:
    """Return registry owner metadata for *name*, if reserved."""
    entries = load_registry()["entries"]
    identity = MachineHoodIdentity.current()
    for candidate in local_agent_name_lookup_candidates(name, identity):
        entry = entries.get(candidate)
        if isinstance(entry, dict):
            return dict(entry)
    return None


def is_name_reserved(name: str, *, load_registry: RegistryLoader) -> bool:
    """Return whether *name* is reserved by an existing agent."""
    entries = load_registry()["entries"]
    identity = MachineHoodIdentity.current()
    return any(
        candidate in entries
        for candidate in local_agent_name_lookup_candidates(name, identity)
    )


def get_reserved_agent_names(*, load_registry: RegistryLoader) -> set[str]:
    """Return every name currently reserved by the registry."""
    return set(load_registry()["entries"])


def get_reserved_clan_names(*, load_registry: RegistryLoader) -> set[str]:
    """Return every name owned by a clan container."""
    return {
        name
        for name, entry in load_registry()["entries"].items()
        if isinstance(entry, dict) and entry.get("container_kind") == "clan"
    }


def get_reserved_family_names(*, load_registry: RegistryLoader) -> set[str]:
    """Return every name owned by a sequential family container."""
    return {
        name
        for name, entry in load_registry()["entries"].items()
        if isinstance(entry, dict) and entry.get("container_kind") == "family"
    }


def get_reserved_agent_name_map(*, load_registry: RegistryLoader) -> dict[str, str]:
    """Return ``{name: owner_path}`` for names with a known owner path."""
    out: dict[str, str] = {}
    for name, entry in load_registry()["entries"].items():
        if not isinstance(entry, dict):
            continue
        owner_path = entry.get("artifacts_dir") or entry.get("bundle_path")
        if isinstance(owner_path, str) and owner_path:
            out[name] = owner_path
    return out


def lowest_name_suggestion(base: str, *, load_registry: RegistryLoader) -> str:
    """Return the lowest available ``<base><N>`` suggestion."""
    identity = MachineHoodIdentity.current()
    visible_base = strip_local_agent_name(base, identity)
    reserved = {
        canonical_local_agent_name_key(name, identity)
        for name in get_reserved_agent_names(load_registry=load_registry)
    }
    n = 1
    while True:
        candidate = f"{visible_base}{n}"
        if canonical_local_agent_name_key(candidate, identity) not in reserved:
            return candidate
        n += 1
