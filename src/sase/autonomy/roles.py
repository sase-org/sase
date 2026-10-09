"""Epic worker role assignments from ``autonomy.roles`` config.

Python glue over core and config. Profile semantics stay in the core
catalog; this module only maps configured role names to ``%auto``
directives.
"""

from __future__ import annotations

import logging
from typing import TypedDict


log = logging.getLogger(__name__)

EPIC_PHASE_ROLE = "epic_phase"
EPIC_LAND_ROLE = "epic_land"
DEFAULT_ROLE_PROFILE = "standard"

_ROLE_ORDER = (EPIC_PHASE_ROLE, EPIC_LAND_ROLE)

_FALLBACK_PROFILE_NAMES = ("manual", "standard", "tale", "epic")


class RoleAssignment(TypedDict):
    """One worker role's effective profile plus where it came from."""

    role: str
    profile: str
    source: str


def _valid_profile_names() -> list[str]:
    """Return known profile names, falling back to built-ins."""
    try:
        from sase.autonomy.record import profiles_catalog

        names = [
            str(item.get("name"))
            for item in profiles_catalog()
            if isinstance(item, dict) and item.get("name")
        ]
        if names:
            return names
    except Exception:
        pass
    return list(_FALLBACK_PROFILE_NAMES)


def _roles_section() -> dict[str, object] | None:
    """Return the merged ``autonomy.roles`` section, or ``None``."""
    try:
        from sase.config import load_merged_config

        merged: object = load_merged_config()
    except Exception:
        return None
    if not isinstance(merged, dict):
        return None
    autonomy = merged.get("autonomy", {})
    if not isinstance(autonomy, dict):
        return None
    roles = autonomy.get("roles", {})
    if not isinstance(roles, dict):
        return None
    return roles


def role_profile(role: str) -> RoleAssignment:
    """Return the effective profile for *role*.

    Missing or malformed sections and non-string values fall back to
    the default. Unknown names also fall back, with a warning, and
    report ``source: invalid``.
    """
    roles = _roles_section()
    if roles is None:
        return {"role": role, "profile": DEFAULT_ROLE_PROFILE, "source": "default"}
    if role not in roles:
        return {"role": role, "profile": DEFAULT_ROLE_PROFILE, "source": "default"}
    raw = roles.get(role)
    if not isinstance(raw, str):
        return {"role": role, "profile": DEFAULT_ROLE_PROFILE, "source": "default"}
    name = raw.strip()
    if not name:
        return {"role": role, "profile": DEFAULT_ROLE_PROFILE, "source": "default"}
    valid = _valid_profile_names()
    if name not in valid:
        log.warning(
            "autonomy.roles.%s: ignoring unknown profile %r (choose from %s)",
            role,
            raw,
            ", ".join(valid),
        )
        return {"role": role, "profile": DEFAULT_ROLE_PROFILE, "source": "invalid"}
    return {"role": role, "profile": name, "source": "config"}


def role_auto_directive(role: str) -> str:
    """Return the ``%auto`` line for *role*'s profile.

    The default-kind catalog entry is selected by bare ``%auto``;
    every other built-in is selected by ``%auto:<name>``. The derived
    selection is verified through ``record.resolve_selection``.
    """
    from sase.autonomy.record import profiles_catalog, resolve_selection

    assignment = role_profile(role)
    profile = assignment["profile"]
    catalog = profiles_catalog()
    entry = next(
        (
            item
            for item in catalog
            if isinstance(item, dict) and item.get("name") == profile
        ),
        None,
    )
    if entry is None:
        raise RuntimeError(
            f"autonomy.roles.{role}: core catalog has no profile {profile!r}"
        )
    if entry.get("kind") == "default":
        selection = ""
        directive = "%auto"
    else:
        selection = profile
        directive = f"%auto:{profile}"
    resolved = resolve_selection(selection, source="prompt", surface="launch")
    if resolved.get("profile") != profile:
        raise RuntimeError(
            f"autonomy.roles.{role}: core and config disagree "
            f"(profile {profile!r} resolved to {resolved.get('profile')!r})"
        )
    return directive


def role_assignments() -> list[RoleAssignment]:
    """Return both role assignments in a fixed order."""
    return [role_profile(role) for role in _ROLE_ORDER]


__all__ = [
    "DEFAULT_ROLE_PROFILE",
    "EPIC_LAND_ROLE",
    "EPIC_PHASE_ROLE",
    "RoleAssignment",
    "role_assignments",
    "role_auto_directive",
    "role_profile",
]
