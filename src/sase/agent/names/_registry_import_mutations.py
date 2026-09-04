"""Registry mutations for imported agent names."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    LegacyV1GroupOwnershipClassification,
    classify_imported_agent_owner,
    current_owner_agent_name_lookup_candidates,
    localize_imported_agent_name,
    validate_owner_root,
)


@dataclass(frozen=True, slots=True)
class ImportedV2RegistryClaim:
    """One run or container claim in an atomic v2 import batch."""

    source_owner: AgentOwnerIdentity
    canonical_global_name: str
    localized_name: str
    claiming_dir: str | Path
    digest: str
    container_kind: str | None = None
    clan_generation: str | None = None
    registry_namespace_root: str | None = None


def claim_imported_registered_name(
    operations: RegistryMutationOperations,
    name: str,
    source_machine: str,
    claiming_dir: str | Path,
    *,
    digest: str,
    target_owner: AgentOwnerIdentity | None = None,
    group_ownership: LegacyV1GroupOwnershipClassification = (
        LegacyV1GroupOwnershipClassification.FOREIGN
    ),
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
    if (
        target_owner is not None
        and source_machine == target_owner.machine_name
        and group_ownership is LegacyV1GroupOwnershipClassification.OWNER_OBSERVED
    ):
        from sase.agent.names._common import ImportedNameCollisionError

        raise ImportedNameCollisionError(
            name,
            reason="the legacy v1 group is owner-observed by this machine",
        )
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
                from sase.agent.names._common import (
                    ImportedNameCollisionError,
                    ImportedNamespaceOwnedLocallyError,
                )

                error_type = (
                    ImportedNamespaceOwnedLocallyError
                    if (
                        existing.get("origin") == "local"
                        and target_owner is not None
                        and source_machine == target_owner.machine_name
                    )
                    else ImportedNameCollisionError
                )
                raise error_type(
                    name,
                    reason="the destination is already reserved by another owner",
                    existing=existing,
                )
        ensure_import_namespace_available(
            entries,
            source_root=source_machine,
            source_owner=None,
            destination_name=name,
            local_owner=target_owner,
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
    claim_imported_registered_names_v2(
        operations,
        (
            ImportedV2RegistryClaim(
                source_owner,
                canonical_global_name,
                localized_name,
                claiming_dir,
                digest,
            ),
        ),
    )


def preflight_imported_registered_names_v2(
    operations: RegistryMutationOperations,
    claims: Sequence[ImportedV2RegistryClaim],
    *,
    identity: AgentIdentitySnapshot | None = None,
    adopted_v1_artifact_dirs: frozenset[Path] = frozenset(),
) -> None:
    """Validate a complete v2 claim batch without saving registry state."""

    if not claims:
        return
    snapshot = identity or AgentIdentitySnapshot.current()
    with operations.lock():
        entries = dict(operations.load()["entries"])
        for claim in claims:
            _apply_imported_v2_registry_claim(
                operations,
                entries,
                claim,
                snapshot,
                adopted_v1_artifact_dirs,
            )


def claim_imported_registered_names_v2(
    operations: RegistryMutationOperations,
    claims: Sequence[ImportedV2RegistryClaim],
    *,
    identity: AgentIdentitySnapshot | None = None,
    adopted_v1_artifact_dirs: frozenset[Path] = frozenset(),
) -> None:
    """Validate and persist every v2 run/container claim in one registry write."""

    if not claims:
        return
    snapshot = identity or AgentIdentitySnapshot.current()
    with operations.lock():
        entries = dict(operations.load()["entries"])
        for claim in claims:
            _apply_imported_v2_registry_claim(
                operations,
                entries,
                claim,
                snapshot,
                adopted_v1_artifact_dirs,
            )
        operations.save_entries(entries)


def _entry_artifact_dir(entry: Mapping[str, Any]) -> Path | None:
    value = entry.get("artifacts_dir")
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser().resolve(strict=False)


def _apply_imported_v2_registry_claim(
    operations: RegistryMutationOperations,
    entries: dict[str, Any],
    claim: ImportedV2RegistryClaim,
    identity: AgentIdentitySnapshot,
    adopted_v1_artifact_dirs: frozenset[Path] = frozenset(),
) -> None:
    source = AgentSourceOwnerIdentity.v2(claim.source_owner)
    expected_name = localize_imported_agent_name(
        claim.canonical_global_name,
        source,
        identity,
    )
    if expected_name != claim.localized_name:
        raise ValueError(
            "localized imported name does not match explicit source ownership: "
            f"expected '{expected_name}', got '{claim.localized_name}'"
        )
    if claim.container_kind not in {None, "family", "clan"}:
        raise ValueError(f"invalid imported container kind {claim.container_kind!r}")

    artifact_dir = Path(claim.claiming_dir).expanduser().resolve(strict=False)
    classification = classify_imported_agent_owner(source, identity)
    source_root: str | None
    if classification is AgentOwnershipClassification.EXACT_OWNER:
        source_root = None
        candidates = current_owner_agent_name_lookup_candidates(
            claim.localized_name,
            identity,
        )
    elif classification is AgentOwnershipClassification.SAME_USER_OTHER_MACHINE:
        source_root = claim.registry_namespace_root or claim.source_owner.machine_name
        validate_owner_root(source_root)
        candidates = (claim.localized_name,)
    else:
        source_root = claim.registry_namespace_root or (
            f"{claim.source_owner.username}.{claim.source_owner.machine_name}"
        )
        validate_owner_root(source_root)
        candidates = (claim.localized_name,)

    if adopted_v1_artifact_dirs:
        username_prefix = f"{claim.source_owner.username}."
        if claim.canonical_global_name.startswith(username_prefix):
            legacy_candidate = claim.canonical_global_name[len(username_prefix) :]
            if legacy_candidate not in candidates:
                candidates = (*candidates, legacy_candidate)

    legacy_username_root: str | None = None
    if (
        classification is AgentOwnershipClassification.OTHER_USER
        and claim.registry_namespace_root is None
        and source_root != claim.source_owner.username
    ):
        legacy_username_root = claim.source_owner.username
        validate_owner_root(legacy_username_root)

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
            and existing.get("canonical_global_name") == claim.canonical_global_name
            and operations.entry_belongs_to_artifact(existing, artifact_dir)
        )
        same_claim = (
            existing.get("origin") == "import_v2"
            and existing.get("canonical_global_name") == claim.canonical_global_name
            and entry_source_owner(existing) == claim.source_owner
            and (
                claim.container_kind is not None
                or operations.entry_belongs_to_artifact(existing, artifact_dir)
            )
            and (
                claim.container_kind is None
                or existing.get("container_kind") == claim.container_kind
            )
        )
        exact_local_container = (
            classification is AgentOwnershipClassification.EXACT_OWNER
            and claim.container_kind is not None
            and existing.get("origin") == "local"
            and existing.get("canonical_global_name") == claim.canonical_global_name
            and existing.get("container_kind") == claim.container_kind
        )
        # A family may have a concrete source run whose global name is also
        # the container identity. Keep the container reservation as the single
        # registry row when both claims share the same artifact owner.
        same_family_root = (
            claim.container_kind is None
            and existing.get("container_kind") == "family"
            and existing.get("origin") == "import_v2"
            and existing.get("canonical_global_name") == claim.canonical_global_name
            and entry_source_owner(existing) == claim.source_owner
            and operations.entry_belongs_to_artifact(existing, artifact_dir)
        )
        adopts_v1_import = (
            existing.get("origin") == "import_v1"
            and existing.get("legacy_source_machine") == claim.source_owner.machine_name
            and _entry_artifact_dir(existing) in adopted_v1_artifact_dirs
        )
        if exact_local_refresh or exact_local_container or same_family_root:
            return
        if not (same_claim or adopts_v1_import):
            from sase.agent.names._common import ImportedNameCollisionError

            raise ImportedNameCollisionError(
                claim.localized_name,
                reason=(
                    "owner, global identity, container kind, or artifact owner "
                    "differs from the existing claim"
                ),
                existing=existing,
            )
    if source_root is not None:
        if legacy_username_root is not None:
            ensure_import_namespace_available(
                entries,
                source_root=legacy_username_root,
                source_owner=claim.source_owner,
                destination_name=claim.localized_name,
            )
        ensure_import_namespace_available(
            entries,
            source_root=source_root,
            source_owner=claim.source_owner,
            destination_name=claim.localized_name,
        )

    reservation_kind = claim.container_kind or "imported"
    entry = operations.owner_from_artifact_name(
        artifact_dir,
        claim.localized_name,
        reservation_kind=reservation_kind,
    )
    entry.update(
        imported_v2_entry_provenance(
            claim.source_owner,
            claim.canonical_global_name,
            claim.digest,
        )
    )
    if claim.container_kind is not None:
        entry["container_kind"] = claim.container_kind
    if claim.container_kind == "clan":
        entry["clan_generation"] = claim.clan_generation or claim.digest[:16]
    if existing_name is not None and existing_name != claim.localized_name:
        entries.pop(existing_name, None)
    if source_root is not None:
        namespace_kind = (
            "sibling_machine"
            if classification is AgentOwnershipClassification.SAME_USER_OTHER_MACHINE
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
                source_owner=claim.source_owner,
            )
    entries[claim.localized_name] = entry
