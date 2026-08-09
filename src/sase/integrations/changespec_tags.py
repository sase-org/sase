"""Legacy compatibility wrapper for Patch xprompt tags."""

from __future__ import annotations

from sase.integrations.patch_tags import (
    PatchTagEntry,
    PatchTagListing,
    list_patch_xprompt_tags,
)

list_changespec_xprompt_tags = list_patch_xprompt_tags  # legacy API alias

__all__ = [
    "PatchTagEntry",
    "PatchTagListing",
    "list_changespec_xprompt_tags",  # legacy API alias
    "list_patch_xprompt_tags",
]
