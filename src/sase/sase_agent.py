"""Shared sase-agent vocabulary for provenance-carrying callers.

A *sase agent* is either an agent family or a single agent that does not
belong to a family.  A *concrete agent shell* is one LLM/provider run; family
members spell that shell with a ``--<role>`` suffix.  Commit provenance,
sidecar publication requests, and plan/bead associations are all anchored on
the sase agent rather than on the concrete shell that happened to make the
commit, so they all need one agreed projection from a shell name to its sase
agent.

``SASE_AGENT_NAME`` identifies the concrete agent shell.  The family
projection and the ``SASE_AGENT=`` commit footer identify the sase agent.

This module is a thin projection over the naming primitives the Rust core
already owns (:func:`parse_agent_family_name`, :func:`agent_link_target`,
:func:`globalize_owned_agent_name`); it deliberately does not re-implement name
parsing.  Everything here is pure apart from one guarded reservation-registry
read in :func:`sase_agent_ref_for_name`.
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
class SaseAgentRef:
    """One resolved sase agent, plus the concrete shell it was derived from."""

    local_name: str
    """Bare local sase-agent name (``pc``), never a member/shell spelling."""

    global_name: str
    """Globally unique sase-agent provenance (``bbugyi200.athena.pc``)."""

    is_family: bool
    """Whether the sase agent is a family/container rather than a solo agent."""

    member_local_name: str | None
    """Bare local concrete-shell name (``pc--code``) when the caller knew one."""


def sase_agent_ref_for_shell(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
) -> SaseAgentRef:
    """Return the sase agent of the concrete agent-shell *name*.

    This is the write-time path: a caller that starts from a real agent-shell
    name knows whether the sase agent is a family for free, because a
    ``--<role>`` suffix is exactly what makes the sase agent a family
    container.  A solo agent shell maps to itself.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    local_name = normalize_owned_agent_name(name, snapshot)
    parsed = parse_agent_family_name(local_name, snapshot)
    is_member = parsed.kind is AgentFamilyNameKind.MEMBER
    return SaseAgentRef(
        local_name=parsed.family_name,
        global_name=globalize_owned_agent_name(parsed.family_name, snapshot),
        is_family=is_member,
        member_local_name=local_name if is_member else None,
    )


def sase_agent_ref_for_name(
    name: str,
    identity: AgentIdentitySnapshot | None = None,
    *,
    reserved_family_names: Collection[str] | None = None,
) -> SaseAgentRef:
    """Return the sase agent described by the already-projected name *name*.

    This is the read-time path, for callers that recovered a sase-agent label
    from a commit footer and have no concrete shell to work from.  ``foo`` is
    lexically ambiguous -- a family container and a solo agent are the same
    string -- so family-ness is resolved through the supplied reservation
    snapshot or the local reservation registry, degrading to a solo sase agent
    when the registry is unavailable or does not know the name.  A member
    spelling is still accepted and projected to its sase agent.
    """
    snapshot = identity or AgentIdentitySnapshot.current()
    local_name = normalize_owned_agent_name(name, snapshot)
    parsed = parse_agent_family_name(local_name, snapshot)
    if parsed.kind is AgentFamilyNameKind.MEMBER:
        return sase_agent_ref_for_shell(local_name, snapshot)
    return SaseAgentRef(
        local_name=local_name,
        global_name=globalize_owned_agent_name(local_name, snapshot),
        is_family=(
            local_name in reserved_family_names
            if reserved_family_names is not None
            else _is_reserved_family_name(local_name)
        ),
        member_local_name=None,
    )


def sase_agent_page_path(
    ref: SaseAgentRef,
    owner: AgentOwnerIdentity,
    identity: AgentIdentitySnapshot | None = None,
) -> str:
    """Return the sidecar page path that durably represents *ref*.

    A known concrete shell is preferred as the input to
    :func:`agent_link_target` so the sidecar layout stays owned by one core
    function; the family page path is only spelled out here when the sase
    agent is known to be a family and no shell is available.
    """
    if ref.member_local_name is not None:
        return agent_link_target(ref.member_local_name, owner, identity).path
    if ref.is_family:
        return f"families/{ref.global_name}.md"
    return agent_link_target(ref.local_name, owner, identity).path


def sase_agent_name(name: str) -> str:
    """Return the bare sase-agent projection of *name*, preserving qualification.

    Unlike :func:`sase_agent_ref_for_shell` this neither normalizes nor
    globalizes, so a global member name yields a global sase-agent name and a
    local one yields a local sase-agent name.  It exists for callers that only
    compare labels.
    """
    return parse_agent_family_name(name).family_name


def _is_reserved_family_name(local_name: str) -> bool:
    """Return whether *local_name* is a registered family container.

    Registry access is best-effort: every caller of this module is a
    provenance boundary that must not fail because the local reservation index
    is missing or unreadable. It is also a labelling read rather than an
    allocation one, so it takes the display tier and never forces a registry
    rebuild, which would hold the name-allocation lock against live launches.
    """
    try:
        from sase.agent.names import get_reserved_family_names_for_display

        return local_name in get_reserved_family_names_for_display()
    except Exception:
        return False


# Narrow compatibility aliases.  New code should use the sase-agent names.
AgentLaneRef = SaseAgentRef
lane_ref_for_agent = sase_agent_ref_for_shell
lane_ref_for_lane_name = sase_agent_ref_for_name
lane_page_path = sase_agent_page_path
lane_name = sase_agent_name


__all__ = [
    "AgentLaneRef",  # legacy compatibility alias
    "SaseAgentRef",
    "lane_name",  # legacy compatibility alias
    "lane_page_path",  # legacy compatibility alias
    "lane_ref_for_agent",  # legacy compatibility alias
    "lane_ref_for_lane_name",  # legacy compatibility alias
    "sase_agent_name",
    "sase_agent_page_path",
    "sase_agent_ref_for_name",
    "sase_agent_ref_for_shell",
]
