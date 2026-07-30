"""Agent-name normalization shared by bead association sources."""

from __future__ import annotations

from sase.agent.bead_display import derive_agent_bead_id_from_name
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    normalize_owned_agent_name,
)
from sase.core.commit_footer_facade import LinkedCommitTagValue


def commit_tag_label(value: object) -> str | None:
    """Return the visible label carried by a parsed commit tag."""

    if isinstance(value, LinkedCommitTagValue):
        return value.label.strip() or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def agent_name_bead_id(
    value: str | None,
    identity: AgentIdentitySnapshot,
) -> str | None:
    """Derive a bead id from local or current-owner global agent spelling."""

    if value is None or not value.strip():
        return None
    candidate = value.strip()
    bead_id = derive_agent_bead_id_from_name(candidate)
    if bead_id is not None:
        return bead_id
    try:
        local_name = normalize_owned_agent_name(candidate, identity)
    except (ImportError, RuntimeError, TypeError, ValueError):
        return None
    return derive_agent_bead_id_from_name(local_name)


__all__ = ["agent_name_bead_id", "commit_tag_label"]
