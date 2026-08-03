"""Entry helpers for the durable agent-name registry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    globalize_owned_agent_name,
)

REGISTRY_ORIGIN_LOCAL = "local"
REGISTRY_ORIGIN_IMPORT_V2 = "import_v2"
REGISTRY_ORIGIN_IMPORT_V1 = "import_v1"


def dotted_namespace_prefixes(name: str) -> set[str]:
    """Return every dotted-segment prefix of *name* (including *name* itself)."""
    parts = name.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def entry_belongs_to_artifact(entry: dict[str, Any], artifact_dir: Path) -> bool:
    existing_dir = entry.get("artifacts_dir")
    if not isinstance(existing_dir, str) or not existing_dir:
        return False
    existing_path = Path(existing_dir).expanduser().resolve(strict=False)
    return existing_path == artifact_dir


def entry_has_other_owner(entry: dict[str, Any], artifact_dir: Path) -> bool:
    if not entry_belongs_to_artifact(entry, artifact_dir):
        return True
    collision_owners = entry.get("collision_owners")
    if not isinstance(collision_owners, list):
        return False
    for owner in collision_owners:
        if isinstance(owner, dict) and not entry_belongs_to_artifact(
            owner, artifact_dir
        ):
            return True
    return False


def entry_has_other_claim_owner(entry: dict[str, Any], artifact_dir: Path) -> bool:
    """Return whether a non-prefix owner belongs to a different artifact."""
    records = [entry]
    collision_owners = entry.get("collision_owners")
    if isinstance(collision_owners, list):
        records.extend(owner for owner in collision_owners if isinstance(owner, dict))
    for record in records:
        if record.get("reservation_kind") == "auto_prefix":
            continue
        if not entry_belongs_to_artifact(record, artifact_dir):
            return True
    return False


def entry_owner_missing(entry: dict[str, Any]) -> bool:
    if entry.get("container_kind") == "owner_namespace":
        return False
    if entry.get("reservation_kind") in {"planned", "planned_clan"}:
        return False
    source = entry.get("source")
    if source == "artifact":
        artifacts_dir = entry.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and not Path(artifacts_dir).exists():
            return True
    elif source == "dismissed_bundle":
        bundle_path = entry.get("bundle_path")
        if isinstance(bundle_path, str) and not Path(bundle_path).is_file():
            return True
    collision_owners = entry.get("collision_owners")
    if isinstance(collision_owners, list):
        for owner in collision_owners:
            if isinstance(owner, dict) and entry_owner_missing(owner):
                return True
    return False


def owner_from_artifact_name(
    artifact_dir: Path,
    name: str,
    *,
    reservation_kind: str,
    template_namespace: str | None = None,
) -> dict[str, Any]:
    info = parse_agent_artifact_path(artifact_dir)
    project_name: str | None
    workflow_name: str
    raw_suffix: str
    if info is not None:
        project_name = info.project_name
        workflow_name = info.workflow_dir_name
        raw_suffix = info.timestamp
    else:
        workflow_dir = artifact_dir.parent
        project_dir = (
            workflow_dir.parent.parent
            if workflow_dir.parent.name == "artifacts"
            else None
        )
        project_name = project_dir.name if project_dir is not None else None
        workflow_name = workflow_dir.name
        raw_suffix = artifact_dir.name
    entry: dict[str, Any] = {
        "source": "artifact",
        "name": name,
        "project_name": project_name,
        "workflow_dir": workflow_name,
        "raw_suffix": raw_suffix,
        "artifacts_dir": str(artifact_dir),
        "state": (
            "planned"
            if reservation_kind == "planned"
            else "done"
            if (artifact_dir / "done.json").exists()
            else "active"
        ),
        "created_at": raw_suffix,
        "reservation_kind": reservation_kind,
    }
    if reservation_kind == "planned":
        entry["reserved_at"] = datetime.now(UTC).isoformat()
    if template_namespace is not None:
        entry["template_namespace"] = template_namespace
    return entry


def _best_effort_canonical_global_name(
    name: str,
    identity: AgentIdentitySnapshot,
) -> str | None:
    """Return canonical global provenance, or ``None`` when it cannot be derived.

    A registry rebuild scans every historical artifact and dismissed bundle,
    so provenance enrichment remains best effort: one un-globalizable name must
    never raise and abort the whole rebuild, which would block every agent
    launch. Such names simply carry no canonical global spelling.
    """
    if identity.owner is None:
        return None
    try:
        return globalize_owned_agent_name(name, identity)
    except ValueError:
        return None


def local_entry_provenance(
    name: str,
    identity: AgentIdentitySnapshot,
) -> dict[str, Any]:
    """Return explicit current-owner provenance for a local registry entry."""
    owner = identity.owner
    return {
        "origin": REGISTRY_ORIGIN_LOCAL,
        "canonical_global_name": _best_effort_canonical_global_name(name, identity),
        "source_owner": (
            {
                "username": owner.username,
                "machine_name": owner.machine_name,
            }
            if owner is not None
            else None
        ),
        "legacy_source_machine": None,
        "imported_digest": None,
    }


def imported_v1_entry_provenance(
    source_machine: str,
    digest: str,
) -> dict[str, Any]:
    """Return username-unknown provenance for a legacy v1 import."""
    return {
        "origin": REGISTRY_ORIGIN_IMPORT_V1,
        "canonical_global_name": None,
        "source_owner": None,
        "legacy_source_machine": source_machine,
        "imported_from_machine": source_machine,
        "imported_digest": digest,
    }


def imported_v2_entry_provenance(
    source_owner: AgentOwnerIdentity,
    canonical_global_name: str,
    digest: str,
) -> dict[str, Any]:
    """Return explicit owner provenance for a v2 imported claim."""
    return {
        "origin": REGISTRY_ORIGIN_IMPORT_V2,
        "canonical_global_name": canonical_global_name,
        "source_owner": {
            "username": source_owner.username,
            "machine_name": source_owner.machine_name,
        },
        "legacy_source_machine": None,
        "imported_digest": digest,
    }


def owner_namespace_entry(
    name: str,
    *,
    namespace_kind: str,
    source_owner: AgentOwnerIdentity | None = None,
) -> dict[str, Any]:
    """Build a synthetic namespace reservation with no artifact owner."""
    return {
        "source": "registry",
        "name": name,
        "origin": (
            REGISTRY_ORIGIN_IMPORT_V2
            if source_owner is not None
            else REGISTRY_ORIGIN_LOCAL
        ),
        "reservation_kind": "owner_namespace",
        "container_kind": "owner_namespace",
        "namespace_kind": namespace_kind,
        "canonical_global_name": None,
        "source_owner": (
            {
                "username": source_owner.username,
                "machine_name": source_owner.machine_name,
            }
            if source_owner is not None
            else None
        ),
        "legacy_source_machine": None,
        "imported_digest": None,
        "state": "reserved",
    }
