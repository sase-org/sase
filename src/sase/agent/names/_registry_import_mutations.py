"""Registry mutations for imported agent names."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.names._registry_entries import (
    imported_v1_entry_provenance,
    imported_v2_entry_provenance,
    owner_namespace_entry,
)
from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations,
    ensure_import_namespace_available,
    entry_source_owner,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    AgentOwnershipClassification,
    AgentSourceOwnerIdentity,
    classify_imported_agent_owner,
    current_owner_agent_name_lookup_candidates,
    localize_imported_agent_name,
)


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
        ensure_import_namespace_available(
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
                and entry_source_owner(existing) == source_owner
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
            ensure_import_namespace_available(
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
