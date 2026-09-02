"""Entry construction and collision handling for registry source scans."""

from __future__ import annotations

from typing import Any

from sase.agent.names._common import extract_auto_name_prefix
from sase.agent.names._registry_entries import (
    imported_v1_entry_provenance,
    imported_v2_entry_provenance,
    local_entry_provenance,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    AgentOwnershipClassification,
    AgentSourceOwnerIdentity,
    classify_imported_agent_owner,
    globalize_agent_name,
    globalize_owned_agent_name,
    localize_imported_agent_name,
    present_agent_name,
)


def add_owner_names(
    entries: dict[str, dict[str, Any]],
    names: set[str],
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> None:
    for name in names:
        _add_owner_name(
            entries,
            name,
            owner,
            provenance_payload,
            identity,
            reservation_kind="claimed",
        )
        prefix = extract_auto_name_prefix(name, identity=identity)
        if prefix is None:
            continue
        # A rebuild preserves the spelling already stored in the artifact.
        # Qualified artifacts therefore derive qualified auto-prefix entries,
        # while legacy bare artifacts remain bare instead of being migrated.
        stored_prefix = _stored_prefix_for_historical_name(name, prefix, identity)
        if stored_prefix not in names:
            _add_owner_name(
                entries,
                stored_prefix,
                owner,
                provenance_payload,
                identity,
                reservation_kind="auto_prefix",
            )


def add_owner_clan(
    entries: dict[str, dict[str, Any]],
    clan: tuple[str, str] | None,
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> None:
    if clan is None:
        return
    name, generation = clan
    entry = {
        **owner,
        **_entry_provenance(name, provenance_payload, identity),
        "name": name,
        "reservation_kind": "clan",
        "container_kind": "clan",
        "clan_generation": generation,
    }
    existing = entries.get(name)
    if not isinstance(existing, dict):
        entries[name] = entry
        return
    if promote_container_over_auto_prefix(entries, name, entry):
        return
    if existing.get("container_kind") == "clan":
        if existing.get("reservation_kind") == "planned_clan" and (
            _entry_owner_identity(existing) == _entry_owner_identity(entry)
        ):
            entries[name] = entry
        return
    _add_owner_name(
        entries,
        name,
        owner,
        provenance_payload,
        identity,
        reservation_kind="claimed",
    )


def add_owner_family(
    entries: dict[str, dict[str, Any]],
    name: str | None,
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> None:
    if name is None:
        return
    entry = {
        **owner,
        **_entry_provenance(name, provenance_payload, identity),
        "name": name,
        "reservation_kind": "family",
        "container_kind": "family",
    }
    existing = entries.get(name)
    if not isinstance(existing, dict):
        entries[name] = entry
        return
    if promote_container_over_auto_prefix(entries, name, entry):
        return
    if existing.get("container_kind") == "family":
        return
    if _entry_owner_identity(existing) == _entry_owner_identity(entry):
        entries[name] = entry
        return
    _add_owner_name(
        entries,
        name,
        owner,
        provenance_payload,
        identity,
        reservation_kind="claimed",
    )


def _add_owner_name(
    entries: dict[str, dict[str, Any]],
    name: str,
    owner: dict[str, Any],
    provenance_payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
    *,
    reservation_kind: str,
) -> None:
    entry = {
        **owner,
        **_entry_provenance(name, provenance_payload, identity),
        "name": name,
        "reservation_kind": reservation_kind,
    }
    existing = entries.get(name)
    if not isinstance(existing, dict):
        entries[name] = entry
        return
    _append_collision_owner(existing, entry)


def promote_container_over_auto_prefix(
    entries: dict[str, dict[str, Any]],
    name: str,
    entry: dict[str, Any],
) -> bool:
    existing = entries.get(name)
    if not isinstance(existing, dict):
        return False
    if existing.get("reservation_kind") != "auto_prefix":
        return False
    previous_collision_owners = existing.get("collision_owners")
    displaced = dict(existing)
    displaced.pop("collision_owners", None)
    entries[name] = entry
    _append_collision_owner(entry, displaced)
    if isinstance(previous_collision_owners, list):
        for owner_entry in previous_collision_owners:
            if isinstance(owner_entry, dict):
                _append_collision_owner(entry, owner_entry)
    return True


def _append_collision_owner(
    existing: dict[str, Any],
    entry: dict[str, Any],
) -> None:
    if _entry_owner_identity(existing) == _entry_owner_identity(entry):
        return
    collision_owners = existing.setdefault("collision_owners", [])
    if not isinstance(collision_owners, list):
        collision_owners = []
        existing["collision_owners"] = collision_owners
    new_identity = _entry_owner_identity(entry)
    for owner_entry in collision_owners:
        if (
            isinstance(owner_entry, dict)
            and _entry_owner_identity(owner_entry) == new_identity
        ):
            return
    collision_owners.append(entry)


def _entry_provenance(
    name: str,
    payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> dict[str, Any]:
    source_owner = source_owner_from_payload(payload)
    canonical_global_name = payload.get("canonical_global_name")
    digest = payload.get("imported_digest")
    if not isinstance(digest, str):
        digest = payload.get("imported_snapshot_digest")
    if (
        source_owner is not None
        and isinstance(canonical_global_name, str)
        and canonical_global_name
        and isinstance(digest, str)
    ):
        return imported_v2_entry_provenance(
            source_owner,
            canonical_global_name,
            digest,
        )
    source_machine = payload.get("imported_from_machine")
    if isinstance(source_machine, str) and source_machine:
        return imported_v1_entry_provenance(
            source_machine,
            digest if isinstance(digest, str) else "",
        )
    return local_entry_provenance(name, identity)


def localize_payload_name(
    name: str,
    payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> str | None:
    """Return *name*'s locally-correct spelling for its payload's provenance.

    Sync preserves an imported artifact's ``name`` field as an already
    localized spelling, but other name fields on the same payload
    (``workflow_name``, family, clan) keep the source machine's bare
    spelling. Registering a bare spelling as a local claim would squat every
    locally-allocated name beneath it, so every payload-derived name must be
    localized through the same import provenance before it reaches the
    registry. Returns ``None`` when the name cannot be localized, so the
    caller drops it instead of registering a squatting spelling.
    """
    source_owner = source_owner_from_payload(payload)
    if source_owner is not None:
        return _localize_v2_payload_name(name, source_owner, identity)
    source_machine = payload.get("imported_from_machine")
    if isinstance(source_machine, str) and source_machine:
        return _localize_v1_payload_name(name, source_machine)
    return name


def _localize_v2_payload_name(
    name: str,
    source_owner: AgentOwnerIdentity,
    identity: AgentIdentitySnapshot,
) -> str | None:
    source = AgentSourceOwnerIdentity.v2(source_owner)
    classification = classify_imported_agent_owner(source, identity)
    if classification is AgentOwnershipClassification.EXACT_OWNER:
        return name
    root = (
        f"{source_owner.machine_name}."
        if classification is AgentOwnershipClassification.SAME_USER_OTHER_MACHINE
        else f"{source_owner.username}."
    )
    if name.startswith(root):
        return name
    global_name = globalize_agent_name(name, source_owner)
    try:
        return localize_imported_agent_name(global_name, source, identity)
    except ValueError:
        return None


def _localize_v1_payload_name(name: str, source_machine: str) -> str | None:
    from sase.agents_sync.io import (
        AgentsSyncFormatError,
        validate_machine,
        validate_qualified_name,
    )

    try:
        machine = validate_machine(source_machine)
    except AgentsSyncFormatError:
        return None
    qualified = name if name.startswith(f"{machine}.") else f"{machine}.{name}"
    try:
        return validate_qualified_name(qualified, machine)
    except AgentsSyncFormatError:
        return None


def source_owner_from_payload(
    payload: dict[str, Any],
) -> AgentOwnerIdentity | None:
    value = payload.get("source_owner")
    if not isinstance(value, dict):
        value = payload.get("imported_source_owner")
    if not isinstance(value, dict):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine_name, str):
        return None
    return AgentOwnerIdentity(username, machine_name)


def _stored_prefix_for_historical_name(
    name: str,
    prefix: str,
    identity: AgentIdentitySnapshot,
) -> str:
    """Keep an auto-prefix beside the historical artifact's exact spelling."""
    owner = identity.owner
    if owner is None or present_agent_name(name, identity) == name:
        return prefix
    if name.startswith(f"{owner.username}.{owner.machine_name}."):
        return globalize_owned_agent_name(prefix, identity)
    if name.startswith(f"{owner.machine_name}."):
        return f"{owner.machine_name}.{prefix}"
    return prefix


def _entry_owner_identity(entry: dict[str, Any]) -> tuple[str, str] | None:
    source = entry.get("source")
    if source == "artifact":
        artifacts_dir = entry.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and artifacts_dir:
            return source, artifacts_dir
    if source == "dismissed_bundle":
        bundle_path = entry.get("bundle_path")
        if isinstance(bundle_path, str) and bundle_path:
            return source, bundle_path
    return None
