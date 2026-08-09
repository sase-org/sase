"""Legacy aliases for patch grouping keys."""

from ..patch_groups._keys import (
    keys_for_patch,
    keys_for_patches,
    sibling_root_for_patch,
    walk_order,
)

keys_for_changespec = keys_for_patch
keys_for_changespecs = keys_for_patches
sibling_root_for_changespec = sibling_root_for_patch

__all__ = [
    "keys_for_changespec",
    "keys_for_changespecs",
    "sibling_root_for_changespec",
    "walk_order",
]
