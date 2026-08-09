"""DELTAS field computation and persistence for Patches."""

from .compute import (
    DeltaComputationError,
    apply_status_mapping,
    compute_deltas,
    resolve_head_ref,
    resolve_parent_ref,
)
from .persistence import (
    PATCH_SECTION_ORDER,
    apply_deltas_update,
    update_changespec_deltas_field,  # legacy compatibility alias
    update_patch_deltas_field,
)
from .refresh import (
    refresh_deltas_after_commits_change,
    refresh_deltas_for_changespec,  # legacy compatibility alias
    refresh_deltas_for_patch,
)

CHANGESPEC_SECTION_ORDER = PATCH_SECTION_ORDER  # legacy compatibility alias

__all__ = [
    "CHANGESPEC_SECTION_ORDER",  # legacy compatibility alias
    "PATCH_SECTION_ORDER",
    "DeltaComputationError",
    "apply_deltas_update",
    "apply_status_mapping",
    "compute_deltas",
    "refresh_deltas_after_commits_change",
    "refresh_deltas_for_changespec",  # legacy compatibility alias
    "refresh_deltas_for_patch",
    "resolve_head_ref",
    "resolve_parent_ref",
    "update_changespec_deltas_field",  # legacy compatibility alias
    "update_patch_deltas_field",
]
