"""One-shot force-reuse bead authorization passed from ACE to a runner."""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from dataclasses import dataclass

SASE_AGENT_FORCE_REUSE_BEAD_ENV = "SASE_AGENT_FORCE_REUSE_BEAD"


@dataclass(frozen=True)
class ForceReuseBeadAssociation:
    """A confirmed forced name replacement tied to one bead association."""

    owner_name: str
    bead_id: str


def _encode_force_reuse_bead_association(
    association: ForceReuseBeadAssociation,
) -> str:
    """Serialize *association* for a child runner environment."""
    return json.dumps(
        {
            "owner_name": association.owner_name,
            "bead_id": association.bead_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def force_reuse_bead_env(
    association: ForceReuseBeadAssociation | None,
) -> dict[str, str]:
    """Return a scoped child environment delta for *association*."""
    if association is None:
        return {}
    return {
        SASE_AGENT_FORCE_REUSE_BEAD_ENV: _encode_force_reuse_bead_association(
            association
        )
    }


def _decode_force_reuse_bead_association(
    raw_value: str | None,
) -> ForceReuseBeadAssociation | None:
    """Parse an environment marker, returning ``None`` for malformed input."""
    if not raw_value:
        return None
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    owner_name = payload.get("owner_name")
    bead_id = payload.get("bead_id")
    if not (
        isinstance(owner_name, str)
        and owner_name
        and isinstance(bead_id, str)
        and bead_id
    ):
        return None
    return ForceReuseBeadAssociation(owner_name=owner_name, bead_id=bead_id)


def consume_force_reuse_bead_association(
    env: MutableMapping[str, str],
) -> ForceReuseBeadAssociation | None:
    """Pop and parse the one-shot force-reuse marker from *env*."""
    return _decode_force_reuse_bead_association(
        env.pop(SASE_AGENT_FORCE_REUSE_BEAD_ENV, None)
    )


__all__ = [
    "ForceReuseBeadAssociation",
    "SASE_AGENT_FORCE_REUSE_BEAD_ENV",
    "consume_force_reuse_bead_association",
    "force_reuse_bead_env",
]
