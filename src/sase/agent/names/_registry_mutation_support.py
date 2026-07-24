"""Shared dependencies and helpers for registry mutations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol

from sase.agent.names._registry_entries import local_entry_provenance
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
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


def local_artifact_entry(
    operations: RegistryMutationOperations,
    artifact_dir: Path,
    name: str,
    *,
    reservation_kind: str,
    identity: AgentIdentitySnapshot,
    template_namespace: str | None = None,
) -> dict[str, Any]:
    """Build a registry entry with provenance for the current owner."""
    entry = operations.owner_from_artifact_name(
        artifact_dir,
        name,
        reservation_kind=reservation_kind,
        template_namespace=template_namespace,
    )
    entry.update(local_entry_provenance(name, identity))
    return entry


def entry_source_owner(entry: Mapping[str, Any]) -> AgentOwnerIdentity | None:
    """Return the explicit source owner stored on an imported entry."""
    value = entry.get("source_owner")
    if not isinstance(value, Mapping):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine_name, str):
        return None
    return AgentOwnerIdentity(username, machine_name)


def ensure_import_namespace_available(
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
            existing_owner = entry_source_owner(raw_entry)
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
        elif source_owner is not None and entry_source_owner(raw_entry) == source_owner:
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


def ensure_local_namespace_available(
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
