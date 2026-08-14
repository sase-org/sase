"""Sase-agent-normalized association hints shared by plan and bead pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    globalize_owned_agent_name,
)
from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.sase_agent import SaseAgentRef, sase_agent_ref_for_shell


class _AgentAssociationLinkResolver(Protocol):
    """The agent-link surface needed to render an association row."""

    def agent_url(self, agent_name: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class AgentAssociationRef:
    """One sase-agent label plus the strongest available link evidence."""

    label: str
    member_local_name: str | None = None
    footer_destination: str | None = None


def artifact_agent_association(
    value: str | None,
    identity: AgentIdentitySnapshot,
) -> AgentAssociationRef | None:
    """Project a concrete artifact agent shell to its sase agent."""

    raw = _nonempty(value)
    if raw is None:
        return None
    try:
        ref = sase_agent_ref_for_shell(raw, identity)
    except (ImportError, RuntimeError, TypeError, ValueError):
        return AgentAssociationRef(_global_name(raw, identity))
    return _artifact_association_from_sase_agent(ref)


def _artifact_association_from_sase_agent(ref: SaseAgentRef) -> AgentAssociationRef:
    return AgentAssociationRef(
        label=ref.global_name,
        member_local_name=ref.member_local_name,
    )


def commit_agent_association(
    value: object,
    identity: AgentIdentitySnapshot,
) -> AgentAssociationRef | None:
    """Project a commit tag to its sase agent without discarding its destination."""

    if isinstance(value, LinkedCommitTagValue):
        raw = _nonempty(value.label)
        destination = _nonempty(value.destination)
    elif isinstance(value, str):
        raw = _nonempty(value)
        destination = None
    else:
        return None
    if raw is None:
        return None
    try:
        label = sase_agent_ref_for_shell(raw, identity).global_name
    except (ImportError, RuntimeError, TypeError, ValueError):
        label = _global_name(raw, identity)
    return AgentAssociationRef(label, footer_destination=destination)


def merge_agent_associations(
    left: AgentAssociationRef | None,
    right: AgentAssociationRef,
) -> AgentAssociationRef:
    """Merge two records for the same sase agent using deterministic evidence."""

    if left is None:
        return right
    if left.label != right.label:
        raise ValueError(f"cannot merge sase agents {left.label!r} and {right.label!r}")
    return AgentAssociationRef(
        label=left.label,
        member_local_name=_preferred(left.member_local_name, right.member_local_name),
        footer_destination=_preferred(
            left.footer_destination,
            right.footer_destination,
        ),
    )


def resolve_agent_association_url(
    association: AgentAssociationRef,
    resolver: _AgentAssociationLinkResolver,
) -> str | None:
    """Resolve an association using shell, footer, then sase-agent evidence."""

    if association.member_local_name is not None:
        target = resolver.agent_url(association.member_local_name)
        if target is not None:
            return target.partition("#")[0]
    if association.footer_destination is not None:
        return association.footer_destination
    return resolver.agent_url(association.label)


def snapshot_agent_name_registry(
    resolver: _AgentAssociationLinkResolver,
    diagnostics: list[str],
) -> None:
    """Let compatible resolvers amortize registry reads across a whole build."""

    snapshot = getattr(resolver, "snapshot_agent_name_registry", None)
    if not callable(snapshot):
        return
    try:
        snapshot()
    except Exception as exc:  # noqa: BLE001 - best-effort link projection.
        diagnostics.append(f"could not snapshot agent-name registry: {exc}")


def _global_name(value: str, identity: AgentIdentitySnapshot) -> str:
    try:
        return globalize_owned_agent_name(value, identity)
    except (ImportError, RuntimeError, TypeError, ValueError):
        return value


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _preferred(left: str | None, right: str | None) -> str | None:
    candidates = tuple(value for value in (left, right) if value is not None)
    return min(candidates) if candidates else None


__all__ = [
    "AgentAssociationRef",
    "artifact_agent_association",
    "commit_agent_association",
    "merge_agent_associations",
    "resolve_agent_association_url",
    "snapshot_agent_name_registry",
]
