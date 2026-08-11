"""Shared AXE Patch candidate filtering."""

from __future__ import annotations

from sase.ace.patch import PR_ORIGIN_EXTERNAL, Patch, normalize_pr_origin


def filter_axe_candidate_patches(patches: list[Patch]) -> list[Patch]:
    """Return patches that AXE is allowed to process."""
    return [
        patch
        for patch in patches
        if normalize_pr_origin(patch.pr_origin) != PR_ORIGIN_EXTERNAL
    ]
