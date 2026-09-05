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
    entry_has_other_claim_owner: Callable[[dict[str, Any], Path], bool]
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
