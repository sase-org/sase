"""Typed Python boundary for explicit agent identity and relationships.

All parsing, ownership classification, validation, graph checks, and ID
rewriting live in :mod:`sase_core_rs`. This module only converts dataclasses
and mappings at the application boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import lru_cache
import json
from pathlib import Path
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
    known_owner_roots: tuple[str, ...] = ()

    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        """Resolve the selected owner and configured sibling machines once."""
        from sase.config import discover_machine_names, get_agent_owner_identity

        owner = get_agent_owner_identity()
        if owner is None:
            return cls(None, (), ())
        siblings = tuple(dict.fromkeys((*discover_machine_names(), owner.machine_name)))
        roots = _discover_known_owner_roots(owner, siblings)
        return cls(owner, siblings, roots)

    @classmethod
    def unconfigured(cls) -> AgentIdentitySnapshot:
        """Return the strict no-owner compatibility snapshot."""
        return cls(None, (), ())


@dataclass(frozen=True, slots=True)
class _ParsedOwnedAgentName:
    owner_root: str | None
    local_name: str
    hood: str
    family_name: str
    member_role: str | None


class AgentOwnershipClassification(StrEnum):
    EXACT_OWNER = "exact_owner"
    SAME_USER_OTHER_MACHINE = "same_user_other_machine"
    OTHER_USER = "other_user"
    USERNAME_UNKNOWN_V1 = "username_unknown_v1"


class AgentFamilyNameKind(StrEnum):
    SOLO = "solo"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class _ParsedAgentFamilyName:
    kind: AgentFamilyNameKind
    family_name: str
    member_role: str | None


class _AgentLinkTargetKind(StrEnum):
    AGENT = "agent"
    FAMILY = "family"


@dataclass(frozen=True, slots=True)
class _AgentLinkTarget:
    kind: _AgentLinkTargetKind
    path: str
    anchor: str | None


@dataclass(frozen=True, slots=True)
class _ValidatedAgentRelationshipSummary:
    schema_version: int
    owner: AgentOwnerIdentity
    run_count: int
    container_count: int
    relationship_count: int
    run_order: tuple[str, ...]
    global_name_order: tuple[str, ...]
    container_order: tuple[str, ...]
    relationship_order: tuple[int, ...]


_DISMISSED_PREFIX_RE = re.compile(r"^(\d{6}\.)(.+)$")
_REGISTRY_FILENAME = "agent_name_registry.json"


@lru_cache(maxsize=32)
def _discover_known_owner_roots(
    owner: AgentOwnerIdentity,
    sibling_machines: tuple[str, ...],
) -> tuple[str, ...]:
    candidates: list[str] = [*sibling_machines]
    candidates.append(owner.machine_name)
    candidates.append(f"{owner.username}.{owner.machine_name}")
    candidates.extend(_registry_owner_roots(owner))
    candidates.extend(_agents_sidecar_owner_roots(owner))
    return _valid_owner_roots(candidates)


def _valid_owner_roots(candidates: Iterable[str]) -> tuple[str, ...]:
    binding = require_rust_binding("validate_owner_root")
    roots: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            binding(candidate)
        except (RuntimeError, ValueError):
            continue
        roots.append(candidate)
    return tuple(
        sorted(dict.fromkeys(roots), key=lambda value: (-value.count("."), value))
    )


def _registry_owner_roots(current_owner: AgentOwnerIdentity) -> tuple[str, ...]:
    try:
        from sase.core.paths import sase_home

        path = sase_home() / _REGISTRY_FILENAME
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(data, dict):
        return ()
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return ()

    roots: list[str] = []
    for name, entry in entries.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if entry.get("container_kind") == "owner_namespace":
            roots.append(name)
        source_owner = _owner_from_untrusted_mapping(entry.get("source_owner"))
        if source_owner is not None:
            roots.extend(_source_owner_roots(source_owner, current_owner))
    return tuple(roots)


def _agents_sidecar_owner_roots(current_owner: AgentOwnerIdentity) -> tuple[str, ...]:
    roots: list[str] = []
    for repo_root in _configured_agents_sidecar_paths():
        users_dir = repo_root / "users"
        if not users_dir.is_dir():
            continue
        try:
            machine_dirs = sorted(
                users_dir.glob("*/machines/*"),
                key=lambda path: path.as_posix(),
            )
        except OSError:
            continue
        for machine_dir in machine_dirs:
            if not machine_dir.is_dir():
                continue
            username = machine_dir.parent.parent.name
            machine_name = machine_dir.name
            owner = AgentOwnerIdentity(username, machine_name)
            roots.extend(_source_owner_roots(owner, current_owner))
            roots.extend(
                _manifest_owner_roots(machine_dir / "manifest.json", current_owner)
            )
    return tuple(roots)


@lru_cache(maxsize=1)
def _configured_agents_sidecar_paths() -> tuple[Path, ...]:
    try:
        from sase.agents_sync.targets import resolve_sync_targets

        selection = resolve_sync_targets()
    except Exception:
        return ()
    paths: list[Path] = []
    for target in selection.targets:
        try:
            paths.append(Path(target.sidecar_path).expanduser().resolve(strict=False))
        except OSError:
            continue
    return tuple(dict.fromkeys(paths))


def _manifest_owner_roots(
    path: Path,
    current_owner: AgentOwnerIdentity,
) -> tuple[str, ...]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(data, dict):
        return ()
    owner = _owner_from_untrusted_mapping(data.get("owner"))
    if owner is None:
        return ()
    return _source_owner_roots(owner, current_owner)


def _owner_from_untrusted_mapping(value: Any) -> AgentOwnerIdentity | None:
    if not isinstance(value, Mapping):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not isinstance(machine_name, str):
        return None
    return AgentOwnerIdentity(username, machine_name)


def _source_owner_roots(
    source_owner: AgentOwnerIdentity,
    current_owner: AgentOwnerIdentity,
) -> tuple[str, ...]:
    canonical = f"{source_owner.username}.{source_owner.machine_name}"
    if source_owner.username == current_owner.username:
        return (source_owner.machine_name, canonical)
    return (canonical,)


def _known_owner_roots(
    snapshot: AgentIdentitySnapshot,
) -> tuple[str, ...]:
    if snapshot.owner is None:
        return ()
    return snapshot.known_owner_roots or _valid_owner_roots(
        (
            *snapshot.sibling_machines,
            snapshot.owner.machine_name,
            f"{snapshot.owner.username}.{snapshot.owner.machine_name}",
        )
    )


def validate_agent_username(username: str) -> None:
    binding = require_rust_binding("validate_agent_username")
    binding(username)


def validate_new_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    """Strictly validate a name the runtime is about to create.

    Historical classification helpers are total on purpose, so a legacy name
    such as ``fi--code.f0`` is read rather than rejected. Name *creation* keeps
    the strict rule: at most one ``--<role>`` suffix, in the final segment.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None:
        binding = require_rust_binding("validate_agent_name")
        binding(name)
        return
    binding = require_rust_binding("validate_owned_agent_name")
    binding(
        name, owner.username, owner.machine_name, list(_known_owner_roots(snapshot))
    )


def validate_agent_owner(owner: AgentOwnerIdentity) -> None:
    binding = require_rust_binding("validate_agent_owner")
    payload = asdict(owner)
    binding(payload["username"], payload["machine_name"])


def _classify_agent_ownership(
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


def _localize_agent_name(
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
    if not name:
        return name
    binding = require_rust_binding("normalize_owned_agent_name")
    return str(
        binding(
            name,
            owner.username,
            owner.machine_name,
            list(_known_owner_roots(snapshot)),
        )
    )


def globalize_owned_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Return canonical global provenance for a current-owned name."""
    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None:
        return name
    binding = require_rust_binding("globalize_owned_agent_name")
    return str(
        binding(
            name,
            owner.username,
            owner.machine_name,
            list(_known_owner_roots(snapshot)),
        )
    )


def localize_imported_agent_name(
    global_name: str,
    source: AgentSourceOwnerIdentity,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Localize one imported name using its explicit source provenance."""
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is None:
        return global_name
    return _localize_agent_name(global_name, source, snapshot.owner)


def classify_imported_agent_owner(
    source: AgentSourceOwnerIdentity,
    identity: AgentIdentitySnapshot | None = None,
) -> AgentOwnershipClassification:
    """Classify explicit imported provenance against the selected owner."""
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is None:
        return AgentOwnershipClassification.USERNAME_UNKNOWN_V1
    return _classify_agent_ownership(source, snapshot.owner)


def present_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Hide only explicit current-owner compatibility prefixes."""
    snapshot = identity or AgentIdentitySnapshot.current()
    if (
        snapshot.owner is not None
        and foreign_agent_owner_root(name, snapshot) is not None
    ):
        return name
    return normalize_owned_agent_name(name, snapshot)


def present_imported_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Return the owner-stripped local spelling for imported display names."""
    snapshot = identity or AgentIdentitySnapshot.current()
    prefix, core_name = _split_dismissed_prefix(name)
    return prefix + _parse_owned_agent_name(core_name, snapshot).local_name


def imported_source_owner_from_mapping(value: object) -> AgentOwnerIdentity | None:
    """Parse a stored ``imported_source_owner`` object, or return ``None``."""
    if not isinstance(value, Mapping):
        return None
    username = value.get("username")
    machine_name = value.get("machine_name")
    if not isinstance(username, str) or not username:
        return None
    if not isinstance(machine_name, str) or not machine_name:
        return None
    return AgentOwnerIdentity(username, machine_name)


def imported_owner_badge_label(
    source: AgentOwnerIdentity,
    destination: AgentOwnerIdentity | None = None,
) -> str:
    """Return the compact owner badge for an imported source owner.

    Same-user foreign machines render as the machine name. Other users render
    as ``username@machine``.
    """
    dest = destination
    if dest is None:
        dest = AgentIdentitySnapshot.current().owner
    if dest is not None and source.username == dest.username:
        return source.machine_name
    return f"{source.username}@{source.machine_name}"


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
    if not name:
        return None
    binding = require_rust_binding("foreign_agent_owner_root")
    value = binding(
        name,
        owner.username,
        owner.machine_name,
        list(_known_owner_roots(snapshot)),
    )
    return str(value) if value is not None else None


def _parse_owned_agent_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> _ParsedOwnedAgentName:
    snapshot = identity or AgentIdentitySnapshot.current()
    roots = _known_owner_roots(snapshot)
    binding = require_rust_binding("parse_owned_agent_name")
    payload: Mapping[str, Any] = binding(name, list(roots))
    return _ParsedOwnedAgentName(
        owner_root=(
            str(payload["owner_root"])
            if payload.get("owner_root") is not None
            else None
        ),
        local_name=str(payload["local_name"]),
        hood=str(payload["hood"]),
        family_name=str(payload["family_name"]),
        member_role=(
            str(payload["member_role"])
            if payload.get("member_role") is not None
            else None
        ),
    )


def parse_agent_family_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> _ParsedAgentFamilyName:
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is not None:
        parsed = _parse_owned_agent_name(name, snapshot)
        return _ParsedAgentFamilyName(
            kind=(
                AgentFamilyNameKind.MEMBER
                if parsed.member_role is not None
                else AgentFamilyNameKind.SOLO
            ),
            family_name=parsed.family_name,
            member_role=parsed.member_role,
        )
    binding = require_rust_binding("parse_agent_family_name")
    payload: Mapping[str, Any] = binding(name)
    return _ParsedAgentFamilyName(
        kind=AgentFamilyNameKind(str(payload["kind"])),
        family_name=str(payload["family_name"]),
        member_role=(
            str(payload["member_role"])
            if payload.get("member_role") is not None
            else None
        ),
    )


def agent_local_hood(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is not None:
        binding = require_rust_binding("agent_local_hood")
        return str(binding(name, list(_known_owner_roots(snapshot))))
    binding = require_rust_binding("agent_local_hood")
    return str(binding(name))


def agent_name_in_hood(
    name: str,
    hood: str,
    identity: AgentIdentitySnapshot | None = None,
) -> bool:
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is not None:
        binding = require_rust_binding("agent_name_in_hood")
        return bool(binding(name, hood, list(_known_owner_roots(snapshot))))
    binding = require_rust_binding("agent_name_in_hood")
    return bool(binding(name, hood))


def agent_name_ancestors(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> tuple[str, ...]:
    snapshot = identity or AgentIdentitySnapshot.current()
    if snapshot.owner is not None:
        binding = require_rust_binding("agent_name_ancestors")
        return tuple(
            str(value) for value in binding(name, list(_known_owner_roots(snapshot)))
        )
    binding = require_rust_binding("agent_name_ancestors")
    return tuple(str(value) for value in binding(name))


def agent_link_target(
    name: str,
    owner: AgentOwnerIdentity,
    identity: AgentIdentitySnapshot | None = None,
) -> _AgentLinkTarget:
    snapshot = identity or AgentIdentitySnapshot(owner)
    if snapshot.owner is not None:
        binding = require_rust_binding("agent_link_target")
        rooted_payload: Mapping[str, Any] = binding(
            name,
            owner.username,
            owner.machine_name,
            list(_known_owner_roots(snapshot)),
        )
        return _AgentLinkTarget(
            kind=_AgentLinkTargetKind(str(rooted_payload["kind"])),
            path=str(rooted_payload["path"]),
            anchor=(
                str(rooted_payload["anchor"])
                if rooted_payload.get("anchor") is not None
                else None
            ),
        )
    binding = require_rust_binding("agent_link_target")
    plain_payload: Mapping[str, Any] = binding(name, owner.username, owner.machine_name)
    return _AgentLinkTarget(
        kind=_AgentLinkTargetKind(str(plain_payload["kind"])),
        path=str(plain_payload["path"]),
        anchor=(
            str(plain_payload["anchor"])
            if plain_payload.get("anchor") is not None
            else None
        ),
    )


def validate_agent_relationship_batch(
    batch: Mapping[str, Any],
) -> _ValidatedAgentRelationshipSummary:
    binding = require_rust_binding("validate_agent_relationship_batch")
    payload: Mapping[str, Any] = binding(dict(batch))
    return _ValidatedAgentRelationshipSummary(
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
    "AgentIdentitySnapshot",
    "AgentOwnerIdentity",
    "AgentOwnershipClassification",
    "AgentSourceOwnerIdentity",
    "agent_link_target",
    "agent_local_hood",
    "agent_name_ancestors",
    "agent_name_in_hood",
    "classify_imported_agent_owner",
    "current_owner_agent_name_key",
    "current_owner_agent_name_lookup_candidates",
    "foreign_agent_owner_root",
    "globalize_agent_name",
    "globalize_owned_agent_name",
    "imported_owner_badge_label",
    "imported_source_owner_from_mapping",
    "localize_imported_agent_name",
    "normalize_owned_agent_name",
    "normalize_agent_archive_name",
    "parse_agent_family_name",
    "present_agent_name",
    "present_imported_agent_name",
    "validate_agent_owner",
    "validate_agent_relationship_batch",
    "validate_agent_username",
    "validate_new_agent_name",
]
