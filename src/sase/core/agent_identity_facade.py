"""Typed Python boundary for explicit agent identity and relationships.

All parsing, ownership classification, validation, graph checks, and ID
rewriting live in :mod:`sase_core_rs`. This module only converts dataclasses
and mappings at the application boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
import re
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True, slots=True)
class AgentOwnerIdentity:
    username: str
    machine_name: str


@dataclass(frozen=True, slots=True)
class AgentSourceOwnerIdentity:
    machine_name: str
    username: str | None = None

    @classmethod
    def v2(cls, owner: AgentOwnerIdentity) -> AgentSourceOwnerIdentity:
        return cls(machine_name=owner.machine_name, username=owner.username)

    @classmethod
    def username_unknown_v1(cls, machine_name: str) -> AgentSourceOwnerIdentity:
        return cls(machine_name=machine_name)


@dataclass(frozen=True, slots=True)
class AgentIdentitySnapshot:
    """One immutable application identity snapshot.

    ``owner`` is absent only for compatibility callers operating before
    identity initialization.  ``sibling_machines`` comes from explicit
    overlay configuration and is used solely for launch/namespace guards; it
    is never used to guess the owner of an arbitrary dotted name.
    """

    owner: AgentOwnerIdentity | None
    sibling_machines: tuple[str, ...] = ()

    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        """Resolve the selected owner and configured sibling machines once."""
        from sase.config import discover_machine_names, get_agent_owner_identity

        owner = get_agent_owner_identity()
        if owner is None:
            return cls(None, ())
        siblings = tuple(dict.fromkeys((*discover_machine_names(), owner.machine_name)))
        return cls(owner, siblings)

    @classmethod
    def unconfigured(cls) -> AgentIdentitySnapshot:
        """Return the strict no-owner compatibility snapshot."""
        return cls(None, ())


class AgentOwnershipClassification(StrEnum):
    EXACT_OWNER = "exact_owner"
    SAME_USER_OTHER_MACHINE = "same_user_other_machine"
    OTHER_USER = "other_user"
    USERNAME_UNKNOWN_V1 = "username_unknown_v1"


class AgentFamilyNameKind(StrEnum):
    SOLO = "solo"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class ParsedAgentFamilyName:
    kind: AgentFamilyNameKind
    family_name: str
    member_role: str | None


class AgentLinkTargetKind(StrEnum):
    AGENT = "agent"
    FAMILY = "family"


@dataclass(frozen=True, slots=True)
class AgentLinkTarget:
    kind: AgentLinkTargetKind
    path: str
    anchor: str | None


@dataclass(frozen=True, slots=True)
class ValidatedAgentRelationshipSummary:
    schema_version: int
    owner: AgentOwnerIdentity
    run_count: int
    container_count: int
    relationship_count: int
    run_order: tuple[str, ...]
    global_name_order: tuple[str, ...]
    container_order: tuple[str, ...]
    relationship_order: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RewrittenAgentRelationshipBatch:
    schema_version: int
    owner: AgentOwnerIdentity
    runs: tuple[Mapping[str, Any], ...]
    containers: tuple[Mapping[str, Any], ...]
    relationships: tuple[Mapping[str, Any], ...]


_DISMISSED_PREFIX_RE = re.compile(r"^(\d{6}\.)(.+)$")


def validate_agent_username(username: str) -> None:
    binding = require_rust_binding("validate_agent_username")
    binding(username)


def validate_agent_owner(owner: AgentOwnerIdentity) -> None:
    binding = require_rust_binding("validate_agent_owner")
    payload = asdict(owner)
    binding(payload["username"], payload["machine_name"])


def classify_agent_ownership(
    source: AgentSourceOwnerIdentity,
    target: AgentOwnerIdentity,
) -> AgentOwnershipClassification:
    binding = require_rust_binding("classify_agent_ownership")
    value = binding(
        source.machine_name,
        target.username,
        target.machine_name,
        source.username,
    )
    return AgentOwnershipClassification(str(value))


def normalize_agent_archive_name(name: str) -> str:
    binding = require_rust_binding("normalize_agent_archive_name")
    return str(binding(name))


def globalize_agent_name(
    local_name: str,
    owner: AgentOwnerIdentity,
) -> str:
    binding = require_rust_binding("globalize_agent_name")
    return str(binding(local_name, owner.username, owner.machine_name))


def globalize_legacy_agent_name(
    legacy_name: str,
    current_owner: AgentOwnerIdentity,
) -> str:
    binding = require_rust_binding("globalize_legacy_agent_name")
    return str(
        binding(
            legacy_name,
            current_owner.username,
            current_owner.machine_name,
        )
    )


def strip_global_agent_name(
    global_name: str,
    source_owner: AgentOwnerIdentity,
) -> str:
    binding = require_rust_binding("strip_global_agent_name")
    return str(
        binding(
            global_name,
            source_owner.username,
            source_owner.machine_name,
        )
    )


def localize_agent_name(
    global_name: str,
    source: AgentSourceOwnerIdentity,
    target: AgentOwnerIdentity,
) -> str:
    binding = require_rust_binding("localize_agent_name")
    return str(
        binding(
            global_name,
            source.machine_name,
            target.username,
            target.machine_name,
            source.username,
        )
    )


def normalize_owned_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Return the bare durable spelling for a newly current-owned name.

    Bare names remain exact.  The current machine-qualified and early fully
    qualified spellings are accepted as compatibility inputs and normalized
    to the same bare semantic name.  Foreign spellings are not localized by
    this function; imports must use :func:`localize_imported_agent_name` with
    an explicit source owner.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None:
        return name
    prefix, core_name = _split_dismissed_prefix(name)
    machine_prefix = f"{owner.machine_name}."
    global_prefix = f"{owner.username}.{owner.machine_name}."
    if core_name.startswith(global_prefix):
        core_name = strip_global_agent_name(core_name, owner)
    elif core_name.startswith(machine_prefix):
        core_name = core_name[len(machine_prefix) :]
    return prefix + core_name


def globalize_owned_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Return canonical global provenance for a current-owned name."""
    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None:
        return name
    prefix, core_name = _split_dismissed_prefix(name)
    bare = normalize_owned_agent_name(core_name, snapshot)
    return prefix + globalize_agent_name(bare, owner)


def localize_imported_agent_name(
    global_name: str,
    source: AgentSourceOwnerIdentity,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Localize one imported name using its explicit source provenance."""
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is None:
        return global_name
    return localize_agent_name(global_name, source, snapshot.owner)


def classify_imported_agent_owner(
    source: AgentSourceOwnerIdentity,
    identity: AgentIdentitySnapshot | None = None,
) -> AgentOwnershipClassification:
    """Classify explicit imported provenance against the selected owner."""
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is None:
        return AgentOwnershipClassification.USERNAME_UNKNOWN_V1
    return classify_agent_ownership(source, snapshot.owner)


def present_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Hide only explicit current-owner compatibility prefixes."""
    return normalize_owned_agent_name(name, identity)


def current_owner_agent_name_lookup_candidates(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> tuple[str, ...]:
    """Return exact-first current-owner compatibility lookup spellings."""
    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None or foreign_agent_owner_root(name, snapshot) is not None:
        return (name,)
    prefix, core_name = _split_dismissed_prefix(name)
    bare = normalize_owned_agent_name(core_name, snapshot)
    return tuple(
        dict.fromkeys(
            (
                name,
                prefix + bare,
                prefix + f"{owner.machine_name}.{bare}",
                prefix + globalize_agent_name(bare, owner),
            )
        )
    )


def current_owner_agent_name_key(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Return the collision key shared by current-owned legacy spellings."""
    snapshot = identity or AgentIdentitySnapshot.current()
    if foreign_agent_owner_root(name, snapshot) is not None:
        return name
    return normalize_owned_agent_name(name, snapshot)


def foreign_agent_owner_root(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str | None:
    """Return an explicitly recognizable foreign owner root for launch guards.

    Recognition is limited to configured machine discriminators.  This keeps
    ``foo.bar`` available as a semantic local name while rejecting spellings
    such as ``zeus.foo``, ``alice.zeus.foo``, and ``bob.athena.foo`` when the
    relevant machine is explicitly configured.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None:
        return None
    _prefix, core_name = _split_dismissed_prefix(name)
    parts = core_name.split(".")
    machines = set(snapshot.sibling_machines)
    if len(parts) >= 2 and parts[0] in machines:
        return parts[0] if parts[0] != owner.machine_name else None
    if len(parts) >= 3 and parts[1] in machines:
        if parts[0] != owner.username or parts[1] != owner.machine_name:
            return f"{parts[0]}.{parts[1]}"
    return None


def parse_agent_family_name(name: str) -> ParsedAgentFamilyName:
    binding = require_rust_binding("parse_agent_family_name")
    payload: Mapping[str, Any] = binding(name)
    return ParsedAgentFamilyName(
        kind=AgentFamilyNameKind(str(payload["kind"])),
        family_name=str(payload["family_name"]),
        member_role=(
            str(payload["member_role"])
            if payload.get("member_role") is not None
            else None
        ),
    )


def agent_local_hood(name: str) -> str:
    binding = require_rust_binding("agent_local_hood")
    return str(binding(name))


def agent_name_in_hood(name: str, hood: str) -> bool:
    binding = require_rust_binding("agent_name_in_hood")
    return bool(binding(name, hood))


def agent_name_ancestors(name: str) -> tuple[str, ...]:
    binding = require_rust_binding("agent_name_ancestors")
    return tuple(str(value) for value in binding(name))


def agent_link_target(
    name: str,
    owner: AgentOwnerIdentity,
) -> AgentLinkTarget:
    binding = require_rust_binding("agent_link_target")
    payload: Mapping[str, Any] = binding(name, owner.username, owner.machine_name)
    return AgentLinkTarget(
        kind=AgentLinkTargetKind(str(payload["kind"])),
        path=str(payload["path"]),
        anchor=(str(payload["anchor"]) if payload.get("anchor") is not None else None),
    )


def agent_relationship_schema_version() -> int:
    binding = require_rust_binding("agent_relationship_schema_version")
    return int(binding())


def validate_agent_relationship_batch(
    batch: Mapping[str, Any],
) -> ValidatedAgentRelationshipSummary:
    binding = require_rust_binding("validate_agent_relationship_batch")
    payload: Mapping[str, Any] = binding(dict(batch))
    return ValidatedAgentRelationshipSummary(
        schema_version=int(payload["schema_version"]),
        owner=_owner_from_mapping(payload["owner"]),
        run_count=int(payload["run_count"]),
        container_count=int(payload["container_count"]),
        relationship_count=int(payload["relationship_count"]),
        run_order=tuple(str(value) for value in payload["run_order"]),
        global_name_order=tuple(str(value) for value in payload["global_name_order"]),
        container_order=tuple(str(value) for value in payload["container_order"]),
        relationship_order=tuple(int(value) for value in payload["relationship_order"]),
    )


def rewrite_agent_relationship_batch(
    batch: Mapping[str, Any],
    destination_ids: Mapping[str, str],
) -> RewrittenAgentRelationshipBatch:
    binding = require_rust_binding("rewrite_agent_relationship_batch")
    payload: Mapping[str, Any] = binding(
        dict(batch),
        dict(destination_ids),
    )
    return RewrittenAgentRelationshipBatch(
        schema_version=int(payload["schema_version"]),
        owner=_owner_from_mapping(payload["owner"]),
        runs=tuple(dict(value) for value in payload["runs"]),
        containers=tuple(dict(value) for value in payload["containers"]),
        relationships=tuple(dict(value) for value in payload["relationships"]),
    )


def _owner_from_mapping(value: Any) -> AgentOwnerIdentity:
    payload: Mapping[str, Any] = value
    return AgentOwnerIdentity(
        username=str(payload["username"]),
        machine_name=str(payload["machine_name"]),
    )


def _split_dismissed_prefix(name: str) -> tuple[str, str]:
    match = _DISMISSED_PREFIX_RE.match(name)
    if match is None:
        return "", name
    return match.group(1), match.group(2)


__all__ = [
    "AgentFamilyNameKind",
    "AgentLinkTarget",
    "AgentLinkTargetKind",
    "AgentIdentitySnapshot",
    "AgentOwnerIdentity",
    "AgentOwnershipClassification",
    "AgentSourceOwnerIdentity",
    "ParsedAgentFamilyName",
    "RewrittenAgentRelationshipBatch",
    "ValidatedAgentRelationshipSummary",
    "agent_link_target",
    "agent_local_hood",
    "agent_name_ancestors",
    "agent_name_in_hood",
    "agent_relationship_schema_version",
    "classify_agent_ownership",
    "classify_imported_agent_owner",
    "current_owner_agent_name_key",
    "current_owner_agent_name_lookup_candidates",
    "foreign_agent_owner_root",
    "globalize_agent_name",
    "globalize_legacy_agent_name",
    "globalize_owned_agent_name",
    "localize_imported_agent_name",
    "localize_agent_name",
    "normalize_owned_agent_name",
    "normalize_agent_archive_name",
    "parse_agent_family_name",
    "present_agent_name",
    "rewrite_agent_relationship_batch",
    "strip_global_agent_name",
    "validate_agent_owner",
    "validate_agent_relationship_batch",
    "validate_agent_username",
]
