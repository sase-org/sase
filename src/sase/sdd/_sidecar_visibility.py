"""Primary-repository visibility policy for sidecar creation."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.sdd._store_types import ATTACHMENTS_SIDECAR_ROLE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sase.sdd._sidecar_init import SidecarInitSpec

PrimaryVisibility = Literal["public", "private", "unknown"]


@dataclass(frozen=True)
class PrimaryRepoVisibility:
    """Parsed visibility of the primary repository's hosted origin."""

    repo: str
    visibility: PrimaryVisibility


@dataclass(frozen=True)
class SidecarVisibilityPolicy:
    """Sidecar specs clamped to a primary repository's visibility."""

    specs: tuple[SidecarInitSpec, ...]
    forced_roles: tuple[str, ...]
    dropped_roles: tuple[str, ...]


def resolve_primary_repo_visibility(
    project_root: Path,
) -> PrimaryRepoVisibility | None:
    """Return the primary checkout's hosted visibility, if resolvable."""

    from sase.workspace_provider._utils_git import run_git_remote_get_url

    try:
        result = run_git_remote_get_url(str(project_root))
    except Exception:
        return None
    if result.returncode != 0:
        return None
    origin_url = (result.stdout or "").strip()
    if not origin_url:
        return None

    from sase._git_remote import parse_hosted_git_remote

    parsed = parse_hosted_git_remote(origin_url)
    if parsed is None:
        return None

    from sase.bead.attachments.remote_visibility import resolve_remote_visibility

    try:
        probed = resolve_remote_visibility(origin_url)
    except Exception:
        probed = "unknown"
    visibility: PrimaryVisibility
    if probed == "public":
        visibility = "public"
    elif probed == "private":
        visibility = "private"
    else:
        visibility = "unknown"
    return PrimaryRepoVisibility(
        repo=parsed.repo,
        visibility=visibility,
    )


def apply_primary_visibility_policy(
    specs: Sequence[SidecarInitSpec],
    primary: PrimaryRepoVisibility | None,
) -> SidecarVisibilityPolicy:
    """Clamp sidecar specs so a non-public primary only gets private sidecars."""

    if primary is None or primary.visibility == "public":
        return SidecarVisibilityPolicy(
            specs=tuple(specs),
            forced_roles=(),
            dropped_roles=(),
        )
    adjusted: list[SidecarInitSpec] = []
    forced_roles: list[str] = []
    dropped_roles: list[str] = []
    for spec in specs:
        if spec.role == ATTACHMENTS_SIDECAR_ROLE:
            dropped_roles.append(spec.role)
            continue
        if spec.visibility.casefold() == "private":
            adjusted.append(spec)
            continue
        adjusted.append(dataclasses.replace(spec, visibility="private"))
        forced_roles.append(spec.role)
    return SidecarVisibilityPolicy(
        specs=tuple(adjusted),
        forced_roles=tuple(forced_roles),
        dropped_roles=tuple(dropped_roles),
    )


def format_visibility_notes(
    policy: SidecarVisibilityPolicy,
    primary: PrimaryRepoVisibility,
) -> tuple[str, ...]:
    """Render the user-facing notes describing a visibility policy result."""

    notes: list[str] = []
    if policy.forced_roles:
        if primary.visibility == "private":
            notes.append(
                f"note: {primary.repo} is private, so SASE creates its "
                "sidecar repositories as private"
            )
        else:
            notes.append(
                f"note: could not verify that {primary.repo} is public, so "
                "SASE creates its sidecar repositories as private"
            )
    if policy.dropped_roles:
        notes.append(
            "note: skipping the public attachments sidecar because "
            f"{primary.repo} is not verified public"
        )
    return tuple(notes)


__all__ = [
    "PrimaryRepoVisibility",
    "PrimaryVisibility",
    "SidecarVisibilityPolicy",
    "apply_primary_visibility_policy",
    "format_visibility_notes",
    "resolve_primary_repo_visibility",
]
