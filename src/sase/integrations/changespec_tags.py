"""Legacy compatibility wrapper for Patch macro tags."""

from __future__ import annotations

from sase.integrations.patch_tags import (
    PatchTagEntry,
    PatchTagListing,
    list_patch_macro_tags,
)

list_changespec_macro_tags = list_patch_macro_tags  # legacy API alias

__all__ = [
    "PatchTagEntry",
    "PatchTagListing",
    "list_changespec_macro_tags",  # legacy API alias
    "list_patch_macro_tags",
]
