"""Legacy REFS persistence names backed by :mod:`sase.ace.patch.refs_persistence`."""

from sase.ace.patch.refs_persistence import (
    apply_refs_update,
    update_changespec_refs_field,
    update_patch_refs_field,
)

_apply_refs_update = apply_refs_update

__all__ = [
    "_apply_refs_update",
    "apply_refs_update",
    "update_changespec_refs_field",
    "update_patch_refs_field",
]
