"""Legacy aliases for patch grouping keys."""

from ..patch_groups._keys import (
    keys_for_patch,
    keys_for_patches,
    sibling_root_for_patch,
    walk_order,
)

keys_for_changespec = keys_for_patch  # legacy compatibility alias
keys_for_changespecs = keys_for_patches  # legacy compatibility alias
sibling_root_for_changespec = sibling_root_for_patch  # legacy compatibility alias

__all__ = [
    "keys_for_changespec",  # legacy compatibility alias
    "keys_for_changespecs",  # legacy compatibility alias
    "sibling_root_for_changespec",  # legacy compatibility alias
    "walk_order",
]
