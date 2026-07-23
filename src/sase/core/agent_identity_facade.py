"""Typed Python boundary for explicit agent identity and relationships.

All parsing, ownership classification, validation, graph checks, and ID
rewriting live in :mod:`sase_core_rs`. This module only converts dataclasses
and mappings at the application boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
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


__all__ = [
    "AgentFamilyNameKind",
    "AgentLinkTarget",
    "AgentLinkTargetKind",
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
    "globalize_agent_name",
    "globalize_legacy_agent_name",
    "localize_agent_name",
    "normalize_agent_archive_name",
    "parse_agent_family_name",
    "rewrite_agent_relationship_batch",
    "strip_global_agent_name",
    "validate_agent_owner",
    "validate_agent_relationship_batch",
    "validate_agent_username",
]
