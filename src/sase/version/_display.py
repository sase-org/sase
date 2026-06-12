"""Display-version derivation for runtime version inventory."""

from __future__ import annotations

from sase.version._models import GitVersionMetadata
from sase.version._utils import version_from_tag


def derive_display_version(
    base_version: str | None,
    git: GitVersionMetadata | None,
) -> str:
    """Return the effective display version for source and git metadata."""
    if git is None:
        return base_version or "<unknown>"

    tag_version = version_from_tag(git.tag)
    if tag_version:
        # A failed distance probe (None) is unknown, not 0 — claiming the
        # bare tag version would misattribute the runtime to the release.
        distance = git.distance
        if distance == 0 and not git.dirty:
            return tag_version
        rendered_distance = "unknown" if distance is None else str(distance)
        suffix = f"{rendered_distance}.g{git.short_commit}"
        if git.dirty:
            suffix = f"{suffix}.dirty"
        return f"{tag_version}+{suffix}"

    if base_version is None:
        return "<unknown>"

    suffix = f"untagged.g{git.short_commit}"
    if git.dirty:
        suffix = f"{suffix}.dirty"
    return f"{base_version}+{suffix}"
