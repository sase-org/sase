"""Projections of the selected raw overlay's agent-owner identity.

Identity is resolved outside the ordinary merge chain so defaults, plugins, the
user base file, ordinary overlays, and project-local config cannot change its
provenance.  :mod:`sase.config.core` owns the cached snapshot; this module only
reads it back and projects it, so the facade stays the single patch point.
"""

from __future__ import annotations

from pathlib import Path

from sase.config.identity import AgentOwnerConfigSnapshot, is_valid_machine_name
from sase.core.agent_identity_facade import AgentOwnerIdentity


def _snapshot() -> AgentOwnerConfigSnapshot:
    """Return the cached identity snapshot through the ``core`` facade.

    The import is deferred because ``core`` imports this module at load time.
    """
    from sase.config.core import get_agent_owner_config_snapshot

    return get_agent_owner_config_snapshot()


def get_agent_owner_identity() -> AgentOwnerIdentity | None:
    """Return the complete owner configured by the selected raw overlay."""
    return _snapshot().owner


def require_agent_owner_identity() -> AgentOwnerIdentity:
    """Return the complete owner or raise with an actionable initializer hint."""
    snapshot = _snapshot()
    if snapshot.owner is None:
        raise RuntimeError(
            "SASE agent owner identity is not configured "
            f"({snapshot.detail}); run `sase config init`."
        )
    return snapshot.owner


def get_machine_name() -> str | None:
    """Compatibility projection of a complete configured owner identity."""
    owner = get_agent_owner_identity()
    return owner.machine_name if owner is not None else None


def require_machine_name() -> str:
    """Compatibility projection requiring a complete configured owner."""
    return require_agent_owner_identity().machine_name


def discover_machine_names() -> tuple[str, ...]:
    """Return valid nested-first machine discriminators from raw overlays."""
    return tuple(
        sorted(
            {
                name
                for overlay in _snapshot().overlays
                if (name := overlay.discriminator) is not None
                and is_valid_machine_name(name)
            }
        )
    )


def selected_overlay_paths() -> list[Path]:
    """Return ordinary overlays plus the overlay selected for this machine.

    Freshness tokens still stat all overlays, so edits to foreign overlays
    invalidate the cached view without parsing them on render-path reads.
    """
    snapshot = _snapshot()
    selected: list[Path] = []
    for overlay in snapshot.overlays:
        if not overlay.declares_machine_overlay:
            selected.append(overlay.path)
        elif overlay.discriminator == snapshot.selector:
            selected.append(overlay.path)
    return selected
