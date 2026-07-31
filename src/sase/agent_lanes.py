"""Shared agent-lane vocabulary for provenance-carrying callers.

An *agent lane* is either an agent family or a single agent that does not
belong to a family.  Commit provenance, sidecar publication requests, and
plan/bead associations are all anchored on the lane rather than on the concrete
family member that happened to make the commit, so they all need one agreed
projection from a member name to its lane.

This module is a thin projection over the naming primitives the Rust core
already owns (:func:`parse_agent_family_name`, :func:`agent_link_target`,
:func:`globalize_owned_agent_name`); it deliberately does not re-implement name
parsing.  Everything here is pure apart from one guarded reservation-registry
read in :func:`lane_ref_for_lane_name`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_link_target,
    globalize_owned_agent_name,
    normalize_owned_agent_name,
    parse_agent_family_name,
)


@dataclass(frozen=True, slots=True)
class AgentLaneRef:
    """One resolved agent lane, plus the member it was derived from."""

    local_name: str
    """Bare local lane name (``pc``), never a member spelling."""

    global_name: str
    """Globally unique lane provenance (``bbugyi200.athena.pc``)."""

    is_family: bool
    """Whether the lane is owned by a sequential family container."""

    member_local_name: str | None
    """Bare local member name (``pc--code``) when the caller knew one."""


def lane_ref_for_agent(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> AgentLaneRef:
    """Return the lane of the concrete agent *name*.

    This is the write-time path: a caller that starts from a real agent name
    knows whether the lane is a family for free, because a ``--<role>`` suffix
    is exactly what makes the lane a family container.  A solo agent maps to
    itself.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    local_name = normalize_owned_agent_name(name, snapshot)
    parsed = parse_agent_family_name(local_name)
    is_member = parsed.kind is AgentFamilyNameKind.MEMBER
    return AgentLaneRef(
        local_name=parsed.family_name,
        global_name=globalize_owned_agent_name(parsed.family_name, snapshot),
        is_family=is_member,
        member_local_name=local_name if is_member else None,
    )


def lane_ref_for_lane_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
    *,
    reserved_family_names: Collection[str] | None = None,
) -> AgentLaneRef:
    """Return the lane described by the bare lane label *name*.

    This is the read-time path, for callers that recovered a lane label from a
    commit footer and have no member to work from.  ``foo`` is lexically
    ambiguous -- a family container and a solo agent are the same string -- so
    family-ness is resolved through the supplied reservation snapshot or the
    local reservation registry, degrading to a solo lane when the registry is
    unavailable or does not know the name.  A member spelling is still accepted
    and projected to its lane.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    local_name = normalize_owned_agent_name(name, snapshot)
    parsed = parse_agent_family_name(local_name)
    if parsed.kind is AgentFamilyNameKind.MEMBER:
        return lane_ref_for_agent(local_name, snapshot)
    return AgentLaneRef(
        local_name=local_name,
        global_name=globalize_owned_agent_name(local_name, snapshot),
        is_family=(
            local_name in reserved_family_names
            if reserved_family_names is not None
            else _is_reserved_family_name(local_name)
        ),
        member_local_name=None,
    )


def lane_page_path(ref: AgentLaneRef, owner: AgentOwnerIdentity) -> str:
    """Return the sidecar page path that durably represents *ref*.

    A known member is preferred as the input to :func:`agent_link_target` so
    the sidecar layout stays owned by one core function; the family page path
    is only spelled out here when the lane is known to be a family and no
    member is available.
    """
    if ref.member_local_name is not None:
        return agent_link_target(ref.member_local_name, owner).path
    if ref.is_family:
        return f"families/{ref.global_name}.md"
    return agent_link_target(ref.local_name, owner).path


def lane_name(name: str) -> str:
    """Return the bare lane projection of *name*, preserving its qualification.

    Unlike :func:`lane_ref_for_agent` this neither normalizes nor globalizes,
    so a global member name yields a global lane name and a local one yields a
    local lane name.  It exists for callers that only compare labels.
    """
    return parse_agent_family_name(name).family_name


def _is_reserved_family_name(local_name: str) -> bool:
    """Return whether *local_name* is a registered family container.

    Registry access is best-effort: every caller of this module is a
    provenance boundary that must not fail because the local reservation index
    is missing or unreadable.
    """
    try:
        from sase.agent.names import get_reserved_family_names

        return local_name in get_reserved_family_names()
    except Exception:
        return False


__all__ = [
    "AgentLaneRef",
    "lane_name",
    "lane_page_path",
    "lane_ref_for_agent",
    "lane_ref_for_lane_name",
]
